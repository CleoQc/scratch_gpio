#!/usr/bin/env python
# ScratchGPIO - control Raspberry Pi GPIO ports using Scratch.
#Copyright (C) 2013 by Simon Walters based on original code for PiFace by Thomas Preston

#This program is free software; you can redistribute it and/or
#modify it under the terms of the GNU General Public License
#as published by the Free Software Foundation; either version 2
#of the License, or (at your option) any later version.

#This program is distributed in the hope that it will be useful,
#but WITHOUT ANY WARRANTY; without even the implied warranty of
#MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#GNU General Public License for more details.

#You should have received a copy of the GNU General Public License
#along with this program; if not, write to the Free Software
#Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.

# This code now hosted on Github thanks to Ben Nuttall
Version =  '3.1.09' # 16Nov13



import threading
import socket
import time
import sys
import struct
import datetime as dt
import shlex
import os
import math
import re
import sgh_GPIOController
import sgh_PiGlow

try:
    from Adafruit_PWM_Servo_Driver import PWM
except:
    pass
#try and inport smbus but don't worry if not installed
#try:
#    from smbus import SMBus
#except:
#    pass

#import RPi.GPIO as GPIO


class Compass:

    __scales = {
        0.88: [0, 0.73],
        1.30: [1, 0.92],
        1.90: [2, 1.22],
        2.50: [3, 1.52],
        4.00: [4, 2.27],
        4.70: [5, 2.56],
        5.60: [6, 3.03],
        8.10: [7, 4.35],
    }

    def __init__(self, port=0, address=0x1E, gauss=1.3, declination=(0,0)):
        self.bus = SMBus(port)
        self.address = address

        (degrees, minutes) = declination
        self.__declDegrees = degrees
        self.__declMinutes = minutes
        self.__declination = (degrees + minutes / 60) * math.pi / 180

        (reg, self.__scale) = self.__scales[gauss]
        self.bus.write_byte_data(self.address, 0x00, 0x70) # 8 Average, 15 Hz, normal measurement
        self.bus.write_byte_data(self.address, 0x01, reg << 5) # Scale
        self.bus.write_byte_data(self.address, 0x02, 0x00) # Continuous measurement

    def declination(self):
        return (self.__declDegrees, self.__declMinutes)

    def twos_complement(self, val, len):
        # Convert twos compliment to integer
        if (val & (1 << len - 1)):
            val = val - (1<<len)
        return val

    def __convert(self, data, offset):
        val = self.twos_complement(data[offset] << 8 | data[offset+1], 16)
        if val == -4096: return None
        return round(val * self.__scale, 4)

    def axes(self):
        data = self.bus.read_i2c_block_data(self.address, 0x00)
        #print map(hex, data)
        x = self.__convert(data, 3)
        y = self.__convert(data, 7)
        z = self.__convert(data, 5)
        return (x,y,z)

    def heading(self):
        (x, y, z) = self.axes()
        headingRad = float(math.atan2(y, x))
        headingRad += self.__declination

        # Correct for reversed heading
        if headingRad < 0:
            headingRad += 2 * math.pi

        # Check for wrap and compensate
        elif headingRad > 2 * math.pi:
            headingRad -= 2 * math.pi

        # Convert to degrees from radians
        headingDeg = headingRad * 180 / math.pi
        degrees = math.floor(headingDeg)
        minutes = round((headingDeg - degrees) * 60)
        return headingDeg

    def degrees(self, (degrees, minutes)):
        return str(degrees) + "*" + str(minutes) + "'"
    
    def degreesdecimal(self, (degrees, minutes)):
        return str(degrees + (minutes /60.0) ) if (degrees >=0) else str(degrees - (minutes /60.0) )

    def __str__(self):
        (x, y, z) = self.axes()
        return "Axis X: " + str(x) + "\n" \
               "Axis Y: " + str(y) + "\n" \
               "Axis Z: " + str(z) + "\n" \
               "dec deg: " + str(self.__declDegrees) + "\n" \
               "dec min: " + str(self.__declMinutes) + "\n" \
               "Declination: " + self.degreesdecimal(self.declination()) + "\n" \
               "Heading: " + str(self.heading()) + "\n"
               
### End Compasss ###################################################################################################



def isNumeric(s):
    try:
        float(s)
        return True
    except ValueError:
        return False
    
def removeNonAscii(s): return "".join(i for i in s if ord(i)<128)
    
def xgetValue(searchString, dataString):
    outputall_pos = dataString.find((searchString + ' '))
    sensor_value = dataString[(outputall_pos+1+len(searchString)):].split()
    return sensor_value[0]
    

def sign(number):return cmp(number,0)


def parse_data(dataraw, search_string):
    outputall_pos = dataraw.find(search_string)
    return dataraw[(outputall_pos + 1 + search_string.length):].split()
    
        
#----------------------------- STEPPER CONTROL --------------
class StepperControl(threading.Thread):
    def __init__(self,pinA,pinB,pinC,pinD,step_delay):
        #self.stepper_num = stepper_num # find which stepper a or b
        #self.step_delay = step_delay
        self.stepperSpeed = 0 #stepp speed dset to 0 when thread created
        self.steps = BIG_NUM # default to psuedo infinte number of turns
        self.terminated = False
        self.toTerminate = False
        threading.Thread.__init__(self)
        self._stop = threading.Event()
        self.pins = [PIN_NUM_LOOKUP[pinA],PIN_NUM_LOOKUP[pinB],PIN_NUM_LOOKUP[pinC],PIN_NUM_LOOKUP[pinD]]
        self.slow_start = self.steps
        self.steps_start = self.steps
        self.paused = False
        self.pause_start_time = dt.datetime.now()

    def start(self):
        self.thread = threading.Thread(None, self.run, None, (), {})
        self.thread.start()


    def stop(self):
        self.toTerminate = True
        while self.terminated == False:
        # Just wait
            time.sleep(0.01)


    def changeSpeed(self, stepperSpeed,steps):
        self.stepperSpeed = int(stepperSpeed)
        self.steps = int(steps)
        self.steps_start = self.steps
        self.slow_start = self.steps - int(min(64,max(1,int(float(self.steps)*0.8))))
        if self.steps > (BIG_NUM / 2):
            self.slow_start = self.steps - 64       
            
    def step_coarse(self,a,b,c,d,delay):
        global stepType
        lstepMode = stepMode[stepType]
        #print stepMode[stepType]
        if lstepMode == '1Coil':
            self.index_pin_update(d,0)
            self.index_pin_update(a,1)
            time.sleep(delay)

            
            self.index_pin_update(b,1)
            self.index_pin_update(a,0)
            time.sleep(delay)
            
            
            self.index_pin_update(c,1)
            self.index_pin_update(b,0)
            time.sleep(delay)
            
            
            self.index_pin_update(d,1)
            self.index_pin_update(c,0)
            time.sleep(delay)
            
        elif lstepMode == '2Coil':
            self.index_pin_update(d,0)
            self.index_pin_update(c,0)
            self.index_pin_update(a,1)
            self.index_pin_update(b,1)

            time.sleep(delay)

            self.index_pin_update(a,0)
            self.index_pin_update(c,1)
            time.sleep(delay)
            
            self.index_pin_update(b,0)
            self.index_pin_update(d,1)
            time.sleep(delay)
            
            self.index_pin_update(c,0)
            self.index_pin_update(a,1)
            time.sleep(delay)
            
        elif lstepMode == 'HalfStep':
            self.index_pin_update(d,0) 
            self.index_pin_update(a,1)
            time.sleep(delay)


            self.index_pin_update(b,1)
            time.sleep(delay)

            self.index_pin_update(a,0)
            time.sleep(delay)
            
            self.index_pin_update(c,1)
            time.sleep(delay)

            self.index_pin_update(b,0)
            time.sleep(delay)

            self.index_pin_update(d,1)
            time.sleep(delay)

            self.index_pin_update(c,0)
            time.sleep(delay)
            
            self.index_pin_update(a,1)
            time.sleep(delay)

    def pause(self):
        self.index_pin_update(self.pins[0],0)
        self.index_pin_update(self.pins[1],0)
        self.index_pin_update(self.pins[2],0)
        self.index_pin_update(self.pins[3],0)
        self.paused = True
        print PIN_NUM[self.pins[0]], "pause method run"




    def run(self):
        #time.sleep(2) # just wait till board likely to be up and running
        self.pause_start_time = dt.datetime.now()
        while self.toTerminate == False:
            #print self.pins[0],self.pins[1],self.pins[2],self.pins[3]

            if (self.steps > 0):
                self.steps = self.steps - 1
                self.local_stepper_value=self.stepperSpeed # get stepper value in case its changed during this thread
                if self.local_stepper_value != 0: #if stepper_value non-zero
                    self.currentStepDelay = step_delay * 100 / abs(self.local_stepper_value)
                    if self.steps < (self.steps_start - self.slow_start) :
                        self.currentStepDelay = self.currentStepDelay *  (3.0 - (((self.steps) / float(self.steps_start - self.slow_start)))*2.0)
                        #print 2.0 - ((self.steps) / float(self.steps_start - self.slow_start))
                    if (self.slow_start < self.steps):
                        #print 2.0 - ((self.steps_start - self.steps) / float(self.steps_start - self.slow_start))
                        self.currentStepDelay = self.currentStepDelay * (3.0 - (((self.steps_start - self.steps) / float(self.steps_start - self.slow_start)))*2.0)
                    #print self.steps, self.currentStepDelay
                    if self.local_stepper_value > 0: # if positive value
                        self.step_coarse(self.pins[0],self.pins[1],self.pins[2],self.pins[3],self.currentStepDelay) #step forward
                    else:
                        self.step_coarse(self.pins[3],self.pins[2],self.pins[1],self.pins[0],self.currentStepDelay) #step forward
##                    if abs(local_stepper_value) != 100: # Only introduce delay if motor not full speed
##                        time.sleep(10*self.step_delay*((100/abs(local_stepper_value))-1))
                    self.pause_start_time = dt.datetime.now()
                    self.paused = False
                    #print PIN_NUM[self.pins[0]],self.pause_start_time
                else:
                    if ((dt.datetime.now() - self.pause_start_time).seconds > 10) and (self.paused == False):
                        self.pause()
                        #print PIN_NUM[self.pins[0]], "paused inner"
                        #print PIN_NUM[self.pins[0]], self.paused
                    #else:
                        #if self.paused == False:
                            #print PIN_NUM[self.pins[0]], "inner" ,(dt.datetime.now() - self.pause_start_time).seconds
                    time.sleep(0.1) # sleep if stepper value is zero
            else:
                if ((dt.datetime.now() - self.pause_start_time).seconds > 10) and (self.paused == False):
                    self.pause()
                    #print PIN_NUM[self.pins[0]], "paused outer"
                    #print PIN_NUM[self.pins[0]], self.paused
                #else:
                    #if self.paused == False:
                        #print PIN_NUM[self.pins[0]], "outer" ,(dt.datetime.now() - self.pause_start_time).seconds
                time.sleep(0.1) # sleep if stepper value is zero

        self.terminated = True
    ####### end of Stepper Class


class MyError(Exception):
    def __init__(self, value):
        self.value = value

    def __str__(self):
        return repr(self.value)

class ScratchSender(threading.Thread):
    def __init__(self, socket):
        threading.Thread.__init__(self)
        self.scratch_socket = socket
        self._stop = threading.Event()
        self.time_last_ping = 0.0
        self.time_last_compass = 0.0
        self.distlist = [0.0,0.0,0.0]


    def stop(self):
        self._stop.set()

    def stopped(self):
        return self._stop.isSet()
        
    def broadcast_changed_pins(self, changed_pin_map, pin_value_map):
        for pin in range(sghGC.numOfPins):
            #print pin
            # if we care about this pin's value
            if (changed_pin_map >> pin) & 0b1:
                #print "changed"
                pin_value = (pin_value_map >> pin) & 0b1
                if (sghGC.pinUse[pin] == sghGC.PINPUT):
                    #print PIN_NUM[i] , pin_value
                    #print "broadcast"
                    self.broadcast_pin_update(pin, pin_value)
                    
                                     
    def broadcast_pin_update(self, pin, value):
        #sensor_name = "gpio" + str(GPIO_NUM[pin_index])
        #bcast_str = 'sensor-update "%s" %d' % (sensor_name, value)
        #print 'sending: %s' % bcast_str
        #self.send_scratch_command(bcast_str)   
        if ADDON_PRESENT[1] == True:
            #do ladderboard stuff
            sensor_name = "switch" + str([0,21,19,24,26].index(pin))
        elif ADDON_PRESENT[2] == True:
            #do MotorPiTx stuff
            if pin == 13:
                sensor_name = "input1"
            if pin == 7:
                sensor_name = "input2"
        elif ADDON_PRESENT[6] == True:
            #do berryclip stuff
            if pin == 26:
                sensor_name = "switch"
        else:
            sensor_name = "pin" + str(pin)
        #if ADDON_PRESENT[5] == True:
            #print PIN_NUM[pin_index] , PIN_NUM[pin_index] in [7,8,10,22]
            #if not(PIN_NUM[pin_index] in [7,8,10,22]):
            #    return
        bcast_str = 'sensor-update "%s" %d' % (sensor_name, value)
        #print 'sending: %s' % bcast_str
        self.send_scratch_command(bcast_str)
        if ADDON_PRESENT[2] == True:
            bcast_str = 'broadcast "%s%s"' % (sensor_name,("Off","On")[value == 1])
            #print 'sending: %s' % bcast_str
            self.send_scratch_command(bcast_str)
        
    def send_scratch_command(self, cmd):
        n = len(cmd)
        b = (chr((n >> 24) & 0xFF)) + (chr((n >> 16) & 0xFF)) + (chr((n >>  8) & 0xFF)) + (chr(n & 0xFF))
        self.scratch_socket.send(b + cmd)

    def run(self):
        global firstRun
        while firstRun:
            time.sleep(1)
        last_bit_pattern=0L
        print sghGC.pinUse
        for pin in range(sghGC.numOfPins):
            if (sghGC.pinUse[pin] == sghGC.PINPUT):
                self.broadcast_pin_update(pin, sghGC.pinRead(pin))
                last_bit_pattern += sghGC.pinRead(pin) << i
            else:
                last_bit_pattern += 1 << i
            #print 'lbp %s' % bin(last_bit_pattern)

        last_bit_pattern = last_bit_pattern ^ -1
        while not self.stopped():
            time.sleep(0.01) # be kind to cpu  :)
            pin_bit_pattern = 0
            for pin in range(sghGC.numOfPins):
                #print pin
                if (sghGC.pinUse[pin] == sghGC.PINPUT):
                    #print 'trying to read pin' , pin 
                    pin_bit_pattern += sghGC.pinRead(pin) << pin
                else:
                    pin_bit_pattern += 1 << pin
                #print bin(pin_bit_pattern) , pin_bit_pattern
            #print bin(pin_bit_pattern) , pin_bit_pattern
            # if there is a change in the input pins
            changed_pins = pin_bit_pattern ^ last_bit_pattern
            #print "changed pins" , bin(changed_pins)
            if changed_pins:
                #print 'pin bit pattern' , bin(pin_bit_pattern)

                try:
                    self.broadcast_changed_pins(changed_pins, pin_bit_pattern)
                except Exception as e:
                    print e
                    break

            last_bit_pattern = pin_bit_pattern

            if (time.time() - self.time_last_ping) > 1: # Check if time to do another ultra ping
                for pin in range(sghGC.numOfPins):
                    if sghGC.pinUse[pin] == sghGC.PULTRA:
                        distance = sghGC.pinSonar(pin) # do a ping
                        sghGC.pinUse[pin] = sghGC.PULTRA # reset pin use back from sonar to ultra
                        sensor_name = 'ultra' + str(pin)
                        if ADDON_PRESENT[2] == True:
                            if pin == 13:
                                sensor_name = "ultra1"
                            if pin == 7:
                                sensor_name = "ultra2"
                                    
                        bcast_str = 'sensor-update "%s" %d' % (sensor_name, distance)
                        #print 'sending: %s' % bcast_str
                        self.send_scratch_command(bcast_str)
                        self.time_last_ping = time.time()
    
            # if (time.time() - self.time_last_compass) > 0.25:
                # #print "time up"
                # #print ADDON_PRESENT[4]
                # #print compass
                # #If Compass board truely present
                # if ((ADDON_PRESENT[4] == True) and (compass != None)):
                    # #print "compass code"
                    # heading = compass.heading()
                    # sensor_name = 'heading'
                    # bcast_str = 'sensor-update "%s" %d' % (sensor_name, heading)
                    # #print 'sending: %s' % bcast_str
                    # self.send_scratch_command(bcast_str)
                # self.time_last_compass = time.time()

            #time.sleep(1)

            
class ScratchListener(threading.Thread):
    def __init__(self, socket):
        threading.Thread.__init__(self)
        self.scratch_socket = socket
        self._stop = threading.Event()
        self.dataraw = ''
        self.value = None
        self.valueNumeric = None
        self.valueIsNumeric = None
        self.OnOrOff = None
        
    def send_scratch_command(self, cmd):
        n = len(cmd)
        b = (chr((n >> 24) & 0xFF)) + (chr((n >> 16) & 0xFF)) + (chr((n >>  8) & 0xFF)) + (chr(n & 0xFF))
        self.scratch_socket.send(b + cmd)
        
    def getValue(self,searchString):
        outputall_pos = self.dataraw.find((searchString + ' '))
        sensor_value = self.dataraw[(outputall_pos+1+len(searchString)):].split()
        return sensor_value[0]
        
    def dFind(self,searchStr):
        return (searchStr in self.dataraw)
        
    def dFindOn(self,searchStr):
        return (self.dFind(searchStr + 'on') or self.dFind(searchStr + 'high'))
        
    def dFindOff(self,searchStr):
        return (self.dFind(searchStr + 'off') or self.dFind(searchStr + 'low'))
        
    def dFindOnOff(self,searchStr):
        self.OnOrOff = None
        if (self.dFind(searchStr + 'on') or self.dFind(searchStr + 'high')):
            self.OnOrOff = 1
            return True
        elif (self.dFind(searchStr + 'off') or self.dFind(searchStr + 'low')):
            self.OnOrOff = 0
            return True
        else:
            return False
            
    # def dRtnOnOff(self,searchStr):
        # if self.dFindOn(searchStr):
            # return 1
        # else:
            # return 0

    def bCheckAll(self):
        if self.dFindOnOff('all'):
            for pin in range(sghGC.numOfPins):
                #print pin
                if sghGC.pinUse[pin] in [sghGC.POUTPUT,sghGC.PPWM]:
                    print pin
                    sghGC.pinUpdate(pin,self.OnOrOff)

    def bpinCheck(self):
        for pin in range(sghGC.numOfPins):
            if self.dFindOnOff('pin' + str(pin)):
                sghGC.pinUpdate(pin,self.OnOrOff)

    def bLEDCheck(self,ledList):
        for led in range(1,(1+ len(ledList))): # loop thru led numbers
            if self.dFindOnOff('led' + str(led)):
                sghGC.pinUpdate(ledList[led - 1],self.OnOrOff)
        
    def vFind(self,searchStr):
        return ((searchStr + ' ') in self.dataraw)
        
    def vFindOn(self,searchStr):
        return (self.vFind(searchStr + 'on') or self.vFind(searchStr + 'high')or self.vFind(searchStr + '1'))
        
    def vFindOff(self,searchStr):
        return (self.vFind(searchStr + 'off') or self.vFind(searchStr + 'low') or self.vFind(searchStr + '0'))
        
    def vFindOnOff(self,searchStr):
        self.value = None
        self.valueNumeric = None
        self.valueIsNumeric = False
        if self.vFind(searchStr):
            self.value = self.getValue(searchStr)
            if str(self.value) in ["high","on","1"]:
                self.valueNumeric = 1
            else:
                self.valueNumeric = 0
            return True
        else:
            return False

    def vFindValue(self,searchStr):
        #print "searching for ", searchStr 
        self.value = None
        self.valueNumeric = None
        self.valueIsNumeric = False
        if self.vFind(searchStr):
            #print "found"
            self.value = self.getValue(searchStr)
            #print self.value
            if isNumeric(self.value):
                self.valueNumeric = float(self.value)
                self.valueIsNumeric = True
                #print "numeric" , self.valueNumeric
            return True
        else:
            return False
            
    def vAllCheck(self,searchStr):
        if self.vFindOnOff(searchStr):
            for pin in range(sghGC.numOfPins):
                if sghGC.pinUse[pin] in [sghGC.POUTPUT,sghGC.PPWM]:
                    sghGC.pinUpdate(pin,self.valueNumeric)

    def vPinCheck(self):
        for pin in range(sghGC.numOfPins):
            if self.vFindValue('pin' + str(pin)):
                if self.valueIsNumeric:
                    sghGC.pinUpdate(pin,self.valueNumeric)
                else:
                    sghGC.pinUpdate(pin,0)
                    
            if self.vFindValue('power' + str(pin)):
                if self.valueIsNumeric:
                    sghGC.pinUpdate(pin,self.valueNumeric,type="pwm")
                else:
                    sghGC.pinUpdate(pin,0,type="pwm")
                    
            if self.vFindValue('motor' + str(pin)):
                if self.valueIsNumeric:
                    sghGC.pinUpdate(pin,self.valueNumeric,type="pwm")
                else:
                    sghGC.pinUpdate(pin,0,type="pwm")
                    
    def vLEDCheck(self,ledList):
        for led in range(1,(1+ len(ledList))): # loop thru led numbers
            if self.vFindValue('led' + str(led)):
                if self.valueIsNumeric:
                    sghGC.pinUpdate(ledList[led - 1],self.valueNumeric)
                else:
                    sghGC.pinUpdate(ledList[led - 1],0)
                    
            if self.vFindValue('power' + str(led)):
                if self.valueIsNumeric:
                    sghGC.pinUpdate(ledList[led - 1],self.valueNumeric,type="pwm")
                else:
                    sghGC.pinUpdate(ledList[led - 1],0,type="pwm")
                    
    def stop(self):
        self._stop.set()

    def stopped(self):
        return self._stop.isSet()

    def step_coarse(self,a,b,c,d,delay):
        self.index_pin_update(a,1)
        self.index_pin_update(d,0)
        time.sleep(delay)

        self.index_pin_update(b,1)
        self.index_pin_update(a,0)
        time.sleep(delay)
        
        self.index_pin_update(c,1)
        self.index_pin_update(b,0)
        time.sleep(delay)
        
        self.index_pin_update(d,1)
        self.index_pin_update(c,0)
        time.sleep(delay)

    def run(self):
        global firstRun,cycle_trace,turnAStep,turnBStep,turnCStep,step_delay,stepType,INVERT, \
               steppera,stepperb,stepperc,Ultra,ultraTotalInUse,piglow,PiGlow_Brightness, \
                   compass

        #firstRun = True #Used for testing in overcoming Scratch "bug/feature"
        firstRunData = ''

        #semi global variables used for servos in PiRoCon
        panoffset = 0
        tiltoffset = 0
        pan = 0
        tilt = 0
        
        #This is main listening routine
        lcount = 0
        while not self.stopped():
            #lcount += 1
            #print lcount
            try:
                #print "try reading socket"
                data = self.scratch_socket.recv(BUFFER_SIZE) # get the data from the socket
                dataraw = data.lower() #[4:].lower() # convert all to lowercase
                print "RAW"
                print dataraw
                #print 'Received from scratch-Length: %d, Data: %s' % (len(dataraw), dataraw)
                
                datarawList = list(dataraw)
                print datarawList
                for m in re.finditer( 'broadcast', dataraw ):
                    print( 'bdcast found', m.start(), m.end() )
                    datarawList[(m.start()-4):(m.start())] = [" "," "," "," "]
                    
                print datarawList
                dataraw = ''.join(datarawList)
                
                if len(dataraw) > 0:
                    dataraw = ' '.join([item.replace(' ','') for item in shlex.split(dataraw)])
                    self.dataraw = dataraw
                    print "Sanitised"
                    print dataraw

                #print 'Cycle trace' , cycle_trace
                if len(dataraw) == 0:
                    #This is probably due to client disconnecting
                    #I'd like the program to retry connecting to the client
                    #tell outer loop that Scratch has disconnected
                    if cycle_trace == 'running':
                        cycle_trace = 'disconnected'
                        break

            except (KeyboardInterrupt, SystemExit):
                #print "reraise error"
                raise
            except socket.timeout:
                #print "No data received: socket timeout"
                continue
            except:
                print "Unknown error occured with receiving data"
                continue
            
            #print "data being processed:" , dataraw
            #This section is only enabled if flag set - I am in 2 minds as to whether to use it or not!
            if firstRun == True:
                anyAddOns = False
                if 'sensor-update' in dataraw:
                    #print "this data ignored" , dataraw
                    firstRunData = dataraw
                    #dataraw = ''
                    #firstRun = False
                    
                    
                    for i in range(NUMOF_ADDON):
                        #print "checking for " , ("addon " + ADDON[i]) 
                        ADDON_PRESENT[i] = False
                        if ("addon " + ADDON[i]) in firstRunData:
                            print "addon " + ADDON[i] + " declared"
                            ADDON_PRESENT[i] = True
                            anyAddOns = True
                            if ADDON[i] == "ladder":
                                ladderOutputs = [11,12,13,15,16,18,22, 7, 5, 3]
                                for pin in ladderOutputs:
                                    sghGC.pinUse[pin] = sghGC.POUTPUT
                                for pin in [24,26,19,21]:
                                    sghGC.pinUse[pin] = sghGC.PINPUT
                                sghGC.setPinMode()
                                    
                            if ADDON[i] == "motorpitx":
                                sghGC.pinUse[11] = sghGC.POUTPUT #Out2 
                                sghGC.pinUse[15] = sghGC.POUTPUT #Out1
                                sghGC.pinUse[16] = sghGC.POUTPUT #Motor2 B
                                sghGC.pinUse[18] = sghGC.POUTPUT #Motor2 A
                                sghGC.pinUse[19] = sghGC.POUTPUT #Motor1
                                sghGC.pinUse[21] = sghGC.POUTPUT #Motor1
                                sghGC.pinUse[22] = sghGC.POUTPUT #Motr 2 Enable
                                sghGC.pinUse[23] = sghGC.POUTPUT #Motor1 Enable
                                
                                sghGC.pinUse[13] = sghGC.PINPUT #Motor1 Enable
                                sghGC.pinUse[7]  = sghGC.PINPUT #Motor1 Enable

                                sghGC.setPinMode()
                                sghGC.startServod([12,10]) # servos
                                print "MotorPiTx setup"

                            if ADDON[i] == "piglow":                                
                                PiGlow_Values = [0] * 18
                                PiGlow_Lookup = [0,1,2,3,14,12,17,16,15,13,11,10,6,7,8,5,4,9]
                                PiGlow_Brightness = 255  

                            if ADDON[i] == "gpio":
                                sghGC.pinUse[11] = sghGC.POUTPUT
                                sghGC.pinUse[12] = sghGC.POUTPUT
                                sghGC.pinUse[13] = sghGC.POUTPUT
                                sghGC.pinUse[15] = sghGC.POUTPUT                                
                                sghGC.pinUse[16] = sghGC.POUTPUT
                                sghGC.pinUse[18] = sghGC.POUTPUT
                                sghGC.pinUse[7]  = sghGC.PINPUT
                                sghGC.pinUse[8]  = sghGC.PINPUT
                                sghGC.pinUse[10] = sghGC.PINPUT
                                sghGC.pinUse[22] = sghGC.PINPUT                                 
                                sghGC.setPinMode()
                                print  "gPiO setup"
                                                               
                            if ADDON[i] == "berry":
                                berryOutputs = [7,11,15,19,21,23,24]
                                for pin in berryOutputs:
                                    sghGC.pinUse[pin] = sghGC.POUTPUT
                                sghGC.pinUse[26] = sghGC.PINPUT

                                sghGC.setPinMode()
                                
                            if ADDON[i] == "pirocon":

                                sghGC.pinUse[19] = sghGC.POUTPUT #MotorA 
                                sghGC.pinUse[21] = sghGC.POUTPUT #MotorB
                                sghGC.pinUse[26] = sghGC.POUTPUT #MotorA 
                                sghGC.pinUse[24] = sghGC.POUTPUT #MotorB
                                sghGC.pinUse[7]  = sghGC.PINPUT #ObsLeft
                                sghGC.pinUse[11] = sghGC.PINPUT #ObsRight
                                sghGC.pinUse[12] = sghGC.PINPUT #LFLeft
                                sghGC.pinUse[13] = sghGC.PINPUT #LFRight

                                sghGC.setPinMode()
                                sghGC.startServod([18,22]) # servos
                                print "pirocon setup"
                                                      
                if anyAddOns == False:
                    print "no AddOns Declared"
                    sghGC.pinUse[11] = sghGC.POUTPUT
                    sghGC.pinUse[12] = sghGC.POUTPUT
                    sghGC.pinUse[13] = sghGC.POUTPUT
                    sghGC.pinUse[15] = sghGC.POUTPUT
                    sghGC.pinUse[16] = sghGC.POUTPUT
                    sghGC.pinUse[18] = sghGC.POUTPUT
                    sghGC.pinUse[7]  = sghGC.PINPUT
                    sghGC.pinUse[22] = sghGC.PINPUT
                    sghGC.setPinMode()
                    
                        
                firstRun = False


            #If outputs need globally inverting (7 segment common anode needs it)
            if ('invert' in dataraw):
                sghGC.INVERT = True
                
            #Change pins from input to output if more needed
            if ('config' in dataraw):
                for i in range(PINS):
                    #check_broadcast = str(i) + 'on'
                    #print check_broadcast
                    physical_pin = PIN_NUM[i]
                    if 'config' + str(physical_pin)+'out' in dataraw: # change pin to output from input
                        if PIN_USE[i] == PINPUT:                           # check to see if it is an input at moment
                            GPIO.setup(PIN_NUM[i],GPIO.OUT)           # make it an output
                            print 'pin' , PIN_NUM[i] , ' out'
                            PIN_USE[i] = POUTPUT
                    if 'config' + str(physical_pin)+'in' in dataraw:                # change pin to input from output
                        if PIN_USE[i] != PINPUT:                                         # check to see if it not an input already
                            GPIO.setup(PIN_NUM[i],GPIO.IN,pull_up_down=GPIO.PUD_UP) # make it an input
                            print 'pin' , PIN_NUM[i] , ' in'
                            PIN_USE[i] = PINPUT
                            
### Check for AddOn boards being declared
                
            #Listen for Variable changes
            if 'sensor-update' in dataraw:
                #print "sensor-update rcvd" , dataraw
                           
              
                if ADDON_PRESENT[1] == True:
                    #do ladderboard stuff

                    self.vAllCheck("leds") # check All LEDS On/Off/High/Low/1/0

                    self.vLEDCheck(ladderOutputs)
                                    
                elif ADDON_PRESENT[2] == True:
                    #do MotorPiTx stuff
                    #check for motor variable commands
                    
                    moveServos = False

                    if self.vFindValue('tiltoffset'):
                        tiltoffset = int(self.valueNumeric) if self.valueIsNumeric else 0
                        moveServos = True

                    if self.vFindValue('panoffset'):
                        panoffset = int(self.valueNumeric) if self.valueIsNumeric else 0
                        moveServos = True
                        
                    if self.vFindValue('tilt'):
                        #print "tilt command rcvd"
                        if self.valueIsNumeric:
                            tilt = int(self.valueNumeric) 
                            moveServos = True
                            #print "tilt=", tilt
                        elif self.value == "off":
                            os.system("echo " + "0" + "=0 > /dev/servoblaster")
                    else:
                        if self.vFindValue('servoa'):
                            #print "tilt command rcvd"
                            if self.valueIsNumeric:
                                tilt = int(self.valueNumeric) 
                                moveServos = True
                                #print "tilt=", tilt
                            elif self.value == "off":
                                sghGC.pinServod(12,"off")
                                
                    if self.vFindValue('pan'):
                        #print "pan command rcvd"
                        if self.valueIsNumeric:
                            pan = int(self.valueNumeric) 
                            moveServos = True
                            #print "pan=", pan
                        elif self.value == "off":
                            os.system("echo " + "1" + "=0 > /dev/servoblaster")
                    else:
                        if self.vFindValue('servob'):
                            #print "pan command rcvd"
                            if self.valueIsNumeric:
                                pan = int(self.valueNumeric) 
                                moveServos = True
                                #print "pan=", pan
                            elif self.value == "off":
                                sghGC.pinServod(10,"off")
                   
                    if moveServos == True:
                        degrees = int(tilt + tiltoffset)
                        degrees = min(80,max(degrees,-60))
                        servodvalue = 50+ ((90 - degrees) * 200 / 180)
                        sghGC.pinServod(12,servodvalue)
                        degrees = int(pan + panoffset)
                        degrees = min(90,max(degrees,-90))
                        servodvalue = 50+ ((90 - degrees) * 200 / 180)
                        sghGC.pinServod(10,servodvalue)


                    #check for motor variable commands
                    motorList = [['motor1',19,21,23],['motor2',18,16,22]]
                    for listLoop in range(0,2):
                        if self.vFindValue(motorList[listLoop][0]):
                            svalue = int(self.valueNumeric) if self.valueIsNumeric else 0
                            # Simple way if all 3 pins are made available - just pwm enable line
                            # if svalue > 0:
                                # sghGC.pinUpdate(motorList[listLoop][1],1) 
                                # sghGC.pinUpdate(motorList[listLoop][2],0)
                                # sghGC.pinUpdate(motorList[listLoop][3],(svalue),"pwm")
                            # elif svalue < 0:
                                # sghGC.pinUpdate(motorList[listLoop][1],0)                    
                                # sghGC.pinUpdate(motorList[listLoop][2],1)
                                # sghGC.pinUpdate(motorList[listLoop][3],(svalue),"pwm")
                            # else:
                                # sghGC.pinUpdate(motorList[listLoop][3],0)                      
                                # sghGC.pinUpdate(motorList[listLoop][1],0)
                                # sghGC.pinUpdate(motorList[listLoop][2],0)
                                
                            # This technique can be used if enabel is held high by hardware
                            if svalue > 0:
                                sghGC.pinUpdate(motorList[listLoop][1],(svalue),"pwm")
                                sghGC.pinUpdate(motorList[listLoop][2],0)
                                sghGC.pinUpdate(motorList[listLoop][3],1)# set enable to 1
                            elif svalue < 0:
                                sghGC.pinUpdate(motorList[listLoop][1],0)            
                                sghGC.pinUpdate(motorList[listLoop][2],(svalue),"pwm")   
                                sghGC.pinUpdate(motorList[listLoop][3],1) # set enable to 1
                            else:
                                sghGC.pinUpdate(motorList[listLoop][3],0)                      
                                sghGC.pinUpdate(motorList[listLoop][1],0)
                                sghGC.pinUpdate(motorList[listLoop][2],0)
                                
                        
                elif ((ADDON_PRESENT[3] == True) and (piglow != None)):
                    #do PiGlow stuff but make sure PiGlow physically detected             
                 
                    #check LEDS
                    for i in range(1,19):
                        if self.vFindValue('led' + str(i)):
                            svalue = int(self.valueNumeric) if self.valueIsNumeric else 0
                            svalue= min(255,max(svalue,0))
                            PiGlow_Values[PiGlow_Lookup[i-1]] = svalue
                            piglow.update_pwm_values(PiGlow_Values)
                            
                    for i in range(1,4):
                        if self.vFindValue('leg' + str(i)):
                            svalue = int(self.valueNumeric) if self.valueIsNumeric else 0
                            svalue= min(255,max(svalue,0))
                            PiGlow_Values[PiGlow_Lookup[((i-1)*6) + 0]] = svalue
                            PiGlow_Values[PiGlow_Lookup[((i-1)*6) + 1]] = svalue
                            PiGlow_Values[PiGlow_Lookup[((i-1)*6) + 2]] = svalue
                            PiGlow_Values[PiGlow_Lookup[((i-1)*6) + 3]] = svalue
                            PiGlow_Values[PiGlow_Lookup[((i-1)*6) + 4]] = svalue
                            PiGlow_Values[PiGlow_Lookup[((i-1)*6) + 5]] = svalue
                            piglow.update_pwm_values(PiGlow_Values)
                            
                        if self.vFindValue('arm' + str(i)):
                            svalue = int(self.valueNumeric) if self.valueIsNumeric else 0
                            svalue= min(255,max(svalue,0))
                            PiGlow_Values[PiGlow_Lookup[((i-1)*6) + 0]] = svalue
                            PiGlow_Values[PiGlow_Lookup[((i-1)*6) + 1]] = svalue
                            PiGlow_Values[PiGlow_Lookup[((i-1)*6) + 2]] = svalue
                            PiGlow_Values[PiGlow_Lookup[((i-1)*6) + 3]] = svalue
                            PiGlow_Values[PiGlow_Lookup[((i-1)*6) + 4]] = svalue
                            PiGlow_Values[PiGlow_Lookup[((i-1)*6) + 5]] = svalue
                            piglow.update_pwm_values(PiGlow_Values)
                            
                    pcolours = ['red','orange','yellow','green','blue','white']
                    for i in range(len(pcolours)):
                        if self.vFindValue(pcolours[i]):
                            svalue = int(self.valueNumeric) if self.valueIsNumeric else 0
                            svalue= min(255,max(svalue,0))
                            PiGlow_Values[PiGlow_Lookup[i+0]] = svalue
                            PiGlow_Values[PiGlow_Lookup[i+6]] = svalue
                            PiGlow_Values[PiGlow_Lookup[i+12]] = svalue
                            piglow.update_pwm_values(PiGlow_Values)
                        
                            
                    #Use bit pattern to control leds
                    if self.vFindValue('ledpattern'):
                        #print 'Found ledpattern'
                        num_of_bits = 18
                        bit_pattern = ('00000000000000000000000000' + self.value)[-num_of_bits:]
                        #print 'led_pattern %s' % bit_pattern
                        j = 0
                        for i in range(18):
                        #bit_state = ((2**i) & sensor_value) >> i
                        #print 'dummy pin %d state %d' % (i, bit_state)
                            if bit_pattern[-(j+1)] == '0':
                                PiGlow_Values[PiGlow_Lookup[i]] = 0
                            else:
                                PiGlow_Values[PiGlow_Lookup[i]] = 1
                            j = j + 1
                        
                        piglow.update_pwm_values(PiGlow_Values)
                        
                    if self.vFindValue('bright'):
                        svalue = int(self.valueNumeric) if self.valueIsNumeric else 0
                        svalue= min(255,max(svalue,0))
                        PiGlow_Brightness = svalue
                        
                elif ADDON_PRESENT[5] == True:
                    #do gPiO stuff
                    
                    self.vAllCheck("allpins") # check Allpins On/Off/High/Low/1/0
 
                    self.vPinCheck() # check for any pin On/Off/High/Low/1/0 any PWM settings using power or motor
                            
                    #check for motor variable commands
                    motorList = [['motora',11,12],['motorb',13,15]]
                    #motorList = [['motora',21,26],['motorb',19,24]]
                    for listLoop in range(0,2):
                        #print motorList[listLoop]
                        checkStr = motorList[listLoop][0]
                        if self.vFind(checkStr):
                            tempValue = getValue(checkStr, dataraw)
                            svalue = int(float(tempValue)) if isNumeric(tempValue) else 0
                            #print "svalue", svalue
                            if svalue > 0:
                                #print motorList[listLoop]
                                #print "motor set forward" , svalue
                                self.pinUpdate(motorList[listLoop][2],1)
                                self.pinUpdate(motorList[listLoop][1],(100-svalue),type="pwm")
                            elif svalue < 0:
                                #print motorList[listLoop]
                                #print "motor set backward", svalue
                                self.pinUpdate(motorList[listLoop][2],0)
                                self.pinUpdate(motorList[listLoop][1],(svalue),type="pwm")
                            else:
                                #print svalue, "zero"
                                self.pinUpdate(motorList[listLoop][1],0)
                                self.pinUpdate(motorList[listLoop][2],0)

                    ######### End of gPiO Variable handling
                   
                elif ADDON_PRESENT[6] == True:
                    #do BerryClip stuff
                    self.vAllCheck("leds") # check All LEDS On/Off/High/Low/1/0

                    self.vLEDCheck(berryOutputs) # check All LEDS On/Off/High/Low/1/0
                                
                    if self.vFindOnOff('buzzer'):
                        self.index_pin_update(24,self.valueNumeric)

                    ######### End of BerryClip Variable handling
                    
                elif ADDON_PRESENT[7] == True:
                    #do PiRoCon stuff
                    #print "panoffset" , panoffset, "tilt",tiltoffset
                    moveServos = False

                    if self.vFindValue('tiltoffset'):
                        tiltoffset = int(self.valueNumeric) if self.valueIsNumeric else 0
                        moveServos = True

                    if self.vFindValue('panoffset'):
                        panoffset = int(self.valueNumeric) if self.valueIsNumeric else 0
                        moveServos = True
                        
                    if self.vFindValue('tilt'):
                        #print "tilt command rcvd"
                        if self.valueIsNumeric:
                            tilt = int(self.valueNumeric) 
                            moveServos = True
                            #print "tilt=", tilt
                        elif self.value == "off":
                            os.system("echo " + "0" + "=0 > /dev/servoblaster")
                    else:
                        if self.vFindValue('servoa'):
                            #print "tilt command rcvd"
                            if self.valueIsNumeric:
                                tilt = int(self.valueNumeric) 
                                moveServos = True
                                #print "tilt=", tilt
                            elif self.value == "off":
                                os.system("echo " + "0" + "=0 > /dev/servoblaster")
                                
                    if self.vFindValue('pan'):
                        #print "pan command rcvd"
                        if self.valueIsNumeric:
                            pan = int(self.valueNumeric) 
                            moveServos = True
                            #print "pan=", pan
                        elif self.value == "off":
                            os.system("echo " + "1" + "=0 > /dev/servoblaster")
                    else:
                        if self.vFindValue('servob'):
                            #print "pan command rcvd"
                            if self.valueIsNumeric:
                                pan = int(self.valueNumeric) 
                                moveServos = True
                                #print "pan=", pan
                            elif self.value == "off":
                                os.system("echo " + "1" + "=0 > /dev/servoblaster")
                   
                    if moveServos == True:
                        degrees = int(tilt + tiltoffset)
                        degrees = min(80,max(degrees,-60))
                        servodvalue = 50+ ((90 - degrees) * 200 / 180)
                        #print "sending", servodvalue, "to servod"
                        #os.system("echo " + "0" + "=" + str(servodvalue-1) + " > /dev/servoblaster")
                        sghGC.pinServod(18,servodvalue)
                        #os.system("echo " + "0" + "=" + str(servodvalue) + " > /dev/servoblaster")
                        degrees = int(pan + panoffset)
                        degrees = min(90,max(degrees,-90))
                        servodvalue = 50+ ((90 - degrees) * 200 / 180)
                        sghGC.pinServod(22,servodvalue)
                        #os.system("echo " + "1" + "=" + str(servodvalue) + " > /dev/servoblaster")


                    #check for motor variable commands
                    motorList = [['motora',21,26],['motorb',19,24]]
                    for listLoop in range(0,2):
                        if self.vFindValue(motorList[listLoop][0]):
                            svalue = int(self.valueNumeric) if self.valueIsNumeric else 0
                            if svalue > 0:
                                sghGC.pinUpdate(motorList[listLoop][2],1)
                                sghGC.pinUpdate(motorList[listLoop][1],(100-svalue),"pwm")
                            elif svalue < 0:
                                sghGC.pinUpdate(motorList[listLoop][2],0)
                                sghGC.pinUpdate(motorList[listLoop][1],(svalue),"pwm")
                            else:
                                sghGC.pinUpdate(motorList[listLoop][1],0)
                                sghGC.pinUpdate(motorList[listLoop][2],0)
                    

                    if (pcaPWM != None):
                        for i in range(0, 16): # go thru servos on PCA Board
                            if self.vFindValue('servo' + str(i + 1)):
                                svalue = int(self.valueNumeric) if self.valueIsNumeric else 180
                                #print i, svalue
                                pcaPWM.setPWM(i, 0, svalue)
                                
                        for i in range(0, 16): # go thru PowerPWM on PCA Board
                            if self.vFindValue('power' + str(i + 1)):
                                svalue = int(self.valueNueric) if self.valueIsNumeric else 0
                                svalue = min(4095,max(((svalue * 4096) /100),0))
                                pcaPWM.setPWM(i, 0, svalue)
                                
                    ######### End of PiRoCon Variable handling
                                                            
                else:   #normal variable processing with no add on board
                    
                    self.vAllCheck("allpins") # check All On/Off/High/Low/1/0
 
                    self.vPinCheck() # check for any pin On/Off/High/Low/1/0 any PWM settings using power or motor
                                
                    checkStr = 'motora'
                    if  (checkStr + ' ') in dataraw:
                        #print "MotorA Received"
                        #print "stepper status" , stepperInUse[STEPPERA]
                        tempValue = getValue(checkStr, dataraw)
                        svalue = int(float(tempValue)) if isNumeric(tempValue) else 0
                        #print "MotorA" , svalue
                        if (stepperInUse[STEPPERA] == True):
                            #print "Stepper A in operation"
                            #print "send change to motora as a stepper" , sensor_value[0]
                            steppera.changeSpeed(max(-100,min(100,svalue)),2123456789)
                            
                        else:
                            i = PIN_NUM_LOOKUP[11] # assume motora is connected to Pin11
                            if PIN_USE[i] != PPWM:
                                PIN_USE[i] = PPWM
                                PWM_OUT[i] = GPIO.PWM(PIN_NUM[i],100)
                                PWM_OUT[i].start(max(0,min(100,svalue)))
                            else:
                                PWM_OUT[i].ChangeDutyCycle(max(0,min(100,svalue)))


                    checkStr = 'motorb'
                    if  (checkStr + ' ') in dataraw:
                        #print "MotorA Received"
                        #print "stepper status" , stepperInUse[STEPPERA]
                        tempValue = getValue(checkStr, dataraw)
                        svalue = int(float(tempValue)) if isNumeric(tempValue) else 0
                        if (stepperInUse[STEPPERB] == True):
                            #print "Stepper B in operation"
                            #print "send change to motorb as a stepper" , sensor_value[0]
                            stepperb.changeSpeed(max(-100,min(100,svalue)),2123456789)
                            
                        else:
                            i = PIN_NUM_LOOKUP[12] # assume motorb is connected to Pin11
                            if PIN_USE[i] != PPWM:
                                PIN_USE[i] = PPWM
                                PWM_OUT[i] = GPIO.PWM(PIN_NUM[i],100)
                                PWM_OUT[i].start(max(0,min(100,svalue)))
                            else:
                                PWM_OUT[i].ChangeDutyCycle(max(0,min(100,svalue)))

                    checkStr = 'motorc'
                    if  (checkStr + ' ') in dataraw:
                        #print "MotorA Received"
                        #print "stepper status" , stepperInUse[STEPPERA]
                        tempValue = getValue(checkStr, dataraw)
                        svalue = int(float(tempValue)) if isNumeric(tempValue) else 0
                        if (stepperInUse[STEPPERC] == True):
                            #print "Stepper C in operation"
                            #print "send change to motorc as a stepper" , sensor_value[0]
                            stepperc.changeSpeed(max(-100,min(100,svalue)),2123456789)
                            
                        else:
                            i = PIN_NUM_LOOKUP[13] # assume motorc is connected to Pin13
                            if PIN_USE[i] != PPWM:
                                PIN_USE[i] = PPWM
                                PWM_OUT[i] = GPIO.PWM(PIN_NUM[i],100)
                                PWM_OUT[i].start(max(0,min(100,svalue)))
                            else:
                                PWM_OUT[i].ChangeDutyCycle(max(0,min(100,svalue)))


                    #Use bit pattern to control ports
                    checkStr = 'pinpattern'
                    if  (checkStr + ' ') in dataraw:
                        #print 'Found pinpattern'
                        num_of_bits = PINS
                        svalue = getValue(checkStr, dataraw)
                        #print sensor_value[0]
                        bit_pattern = ('00000000000000000000000000'+svalue)[-num_of_bits:]
                        #print 'bit_pattern %s' % bit_pattern
                        j = 0
                        for i in range(PINS):
                        #bit_state = ((2**i) & sensor_value) >> i
                        #print 'dummy pin %d state %d' % (i, bit_state)
                            if (PIN_USE[i] == POUTPUT):
                                if bit_pattern[-(j+1)] == '0':
                                    self.index_pin_update(i,0)
                                else:
                                    self.index_pin_update(i,1)
                                j = j + 1

                                           



                    checkStr = 'stepdelay'
                    if  (checkStr + ' ') in dataraw:
                        #print "MotorA Received"
                        #print "stepper status" , stepperInUse[STEPPERA]
                        tempValue = getValue(checkStr, dataraw)
                        if isNumeric(tempValue):
                            step_delay = int(float(tempValue))
                            print 'step delay changed to', step_delay

                    if  'positiona' in dataraw:
                        #print "positiona" , dataraw
                        if (stepperInUse[STEPPERA] == True):
                            outputall_pos = dataraw.find('positiona')
                            sensor_value = dataraw[(outputall_pos+1+len('positiona')):].split()
                            if isNumeric(sensor_value[0]):
                                #if int(float(sensor_value[0])) != 0:s
                                if 'steppera' in dataraw:
                                    turnAStep = int(float(sensor_value[0]))
                                else:
                                    steppera.changeSpeed(int(100 * sign(int(float(sensor_value[0])) - turnAStep)),abs(int(float(sensor_value[0])) - turnAStep))
                                    turnAStep = int(float(sensor_value[0]))
                                    #else:
                                    #    turnAStep = 0
                                                
                    if  'positionb' in dataraw:
                        #print "positionb" , dataraw
                        if (stepperInUse[STEPPERB] == True):
                            outputall_pos = dataraw.find('positionb')
                            sensor_value = dataraw[(outputall_pos+1+len('positionb')):].split()
                            #print "sensor" , sensor_value[0]
                            if isNumeric(sensor_value[0]):
                                #if int(float(sensor_value[0])) != 0:
                                if 'stepperb' in dataraw:
                                    turnBStep = int(float(sensor_value[0]))
                                    #print "stepperb found"
                                else:
                                    #print "change posb" , sensor_value[0]
                                    stepperb.changeSpeed(int(100 * sign(int(float(sensor_value[0])) - turnBStep)),abs(int(float(sensor_value[0])) - turnBStep))
                                    turnBStep = int(float(sensor_value[0]))
                                    #else:
                                    #    turnBStep = 0

                    if  'positionc' in dataraw:
                        print "positionc" , dataraw
                        if (stepperInUse[STEPPERC] == True):
                            outputall_pos = dataraw.find('positionc')
                            sensor_value = dataraw[(outputall_pos+1+len('positionc')):].split()
                            #print "sensor" , sensor_value[0]
                            if isNumeric(sensor_value[0]):
                                #if int(float(sensor_value[0])) != 0:
                                if 'stepperc' in dataraw:
                                    turnCStep = int(float(sensor_value[0]))
                                    #print "stepperb found"
                                else:
                                    #print "change posb" , sensor_value[0]
                                    stepperc.changeSpeed(int(100 * sign(int(float(sensor_value[0])) - turnCStep)),abs(int(float(sensor_value[0])) - turnCStep))
                                    turnCStep = int(float(sensor_value[0]))
                                    #else:
                                    #    turnBStep = 0
            
                            

### Check for Broadcast type messages being received
            if 'broadcast' in dataraw:
                #print 'broadcast in data:' , dataraw

                if ADDON_PRESENT[1] == True: # Gordon's Ladder Board
                    #do ladderboard stuff
                    #print ("Ladder broadcast processing")                    
                    self.bCheckAll() # Check for all off/on type broadcasrs
                    self.bLEDCheck(ladderOutputs) # Check for LED off/on type broadcasts
                            
                elif ADDON_PRESENT[2] == True: # Boeeerb MotorPiTx

                    if ('sonar1') in dataraw:
                        distance = sghGC.pinSonar(13)
                        #print'Distance:',distance,'cm'
                        sensor_name = 'sonar' + str(13)
                        bcast_str = 'sensor-update "%s" %d' % (sensor_name, distance)
                        #print 'sending: %s' % bcast_str
                        self.send_scratch_command(bcast_str)
                        
                    if ('sonar2') in dataraw:
                        distance = sghGC.pinSonar(7)
                        #print'Distance:',distance,'cm'
                        sensor_name = 'sonar' + str(7)
                        bcast_str = 'sensor-update "%s" %d' % (sensor_name, distance)
                        #print 'sending: %s' % bcast_str
                        self.send_scratch_command(bcast_str)                        
                        
                    if self.dFind('ultra1'):
                        print 'start pinging on', str(13)
                        sghGC.pinUse[13] = sghGC.PULTRA
                        
                    if self.dFind('ultra2'):
                        print 'start pinging on', str(7)
                        sghGC.pinUse[7] = sghGC.PULTRA
                        
                elif ((ADDON_PRESENT[3] == True) and (piglow != None)): # Pimoroni PiGlow
                
                    if self.dFindOnOff('all'):
                        for i in range(1,19):
                            PiGlow_Values[i-1] = PiGlow_Brightness * self.OnOrOff
                            piglow.update_pwm_values(PiGlow_Values)
                             
                    #check LEDS
                    for i in range(1,19):
                        #check_broadcast = str(i) + 'on'
                        #print check_broadcast
                        if self.dFindOnOff('led'+str(i)):
                            #print dataraw
                            PiGlow_Values[PiGlow_Lookup[i-1]] = PiGlow_Brightness * self.OnOrOff
                            piglow.update_pwm_values(PiGlow_Values)

                        if self.dFindOnOff('light'+str(i)):
                            #print dataraw
                            PiGlow_Values[PiGlow_Lookup[i-1]] = PiGlow_Brightness * self.OnOrOff
                            piglow.update_pwm_values(PiGlow_Values)
                            
                    pcolours = ['red','orange','yellow','green','blue','white']
                    for i in range(len(pcolours)):
                        if self.dFindOnOff(pcolours[i]):
                            #print dataraw
                            PiGlow_Values[PiGlow_Lookup[i+0]] = PiGlow_Brightness * self.OnOrOff
                            PiGlow_Values[PiGlow_Lookup[i+6]] = PiGlow_Brightness * self.OnOrOff
                            PiGlow_Values[PiGlow_Lookup[i+12]] = PiGlow_Brightness * self.OnOrOff
                            piglow.update_pwm_values(PiGlow_Values)
                                                       
                    for i in range(1,4):
                        if self.dFindOnOff('leg'+str(i)):
                            #print dataraw
                            PiGlow_Values[PiGlow_Lookup[((i-1)*6) + 0]] = PiGlow_Brightness * self.OnOrOff
                            PiGlow_Values[PiGlow_Lookup[((i-1)*6) + 1]] = PiGlow_Brightness * self.OnOrOff
                            PiGlow_Values[PiGlow_Lookup[((i-1)*6) + 2]] = PiGlow_Brightness * self.OnOrOff
                            PiGlow_Values[PiGlow_Lookup[((i-1)*6) + 3]] = PiGlow_Brightness * self.OnOrOff
                            PiGlow_Values[PiGlow_Lookup[((i-1)*6) + 4]] = PiGlow_Brightness * self.OnOrOff
                            PiGlow_Values[PiGlow_Lookup[((i-1)*6) + 5]] = PiGlow_Brightness * self.OnOrOff
                            piglow.update_pwm_values(PiGlow_Values)
                            
                        if self.dFindOnOff('arm'+str(i)):
                            #print dataraw
                            PiGlow_Values[PiGlow_Lookup[((i-1)*6) + 0]] = PiGlow_Brightness * self.OnOrOff
                            PiGlow_Values[PiGlow_Lookup[((i-1)*6) + 1]] = PiGlow_Brightness * self.OnOrOff
                            PiGlow_Values[PiGlow_Lookup[((i-1)*6) + 2]] = PiGlow_Brightness * self.OnOrOff
                            PiGlow_Values[PiGlow_Lookup[((i-1)*6) + 3]] = PiGlow_Brightness * self.OnOrOff
                            PiGlow_Values[PiGlow_Lookup[((i-1)*6) + 4]] = PiGlow_Brightness * self.OnOrOff
                            PiGlow_Values[PiGlow_Lookup[((i-1)*6) + 5]] = PiGlow_Brightness * self.OnOrOff
                            piglow.update_pwm_values(PiGlow_Values)

                elif ADDON_PRESENT[5] == True: # gPiO
                    #print ("gPiO broadcast processing")
                    self.bCheckAll() # Check for all off/on type broadcasts
                    self.bpinCheck() # Check for pin off/on type broadcasts
                
                elif ADDON_PRESENT[6] == True: # BerryClip

                    #print ("Berry broadcast processing")                    
                    self.bCheckAll() # Check for all off/on type broadcasts
                    self.bLEDCheck(berryOutputs) # Check for LED off/on type broadcasts
                    if self.dFindOnOff('buzzer'):
                        sghGC.pinUpdate(24,self.OnOrOff)                                         
   
                else: # Plain GPIO Broadcast processing

                    self.bCheckAll() # Check for all off/on type broadcasrs
                    self.bpinCheck() # Check for pin off/on type broadcasts
                                
                    #check pins
                    for pin in range(sghGC.numOfPins):
                        if self.dFindOnOff('pin' + str(pin)):
                            sghGC.pinUpdate(pin,self.OnOrOff)

                        if ('sonar' + str(pin)) in dataraw:
                            distance = sghGC.pinSonar(pin)
                            #print'Distance:',distance,'cm'
                            sensor_name = 'sonar' + str(pin)
                            bcast_str = 'sensor-update "%s" %d' % (sensor_name, distance)
                            #print 'sending: %s' % bcast_str
                            self.send_scratch_command(bcast_str)
                            
                        #Start using ultrasonic sensor on a pin    
                        if self.dFind('ultra' + str(pin)):
                            print 'start pinging on', str(pin)
                            sghGC.pinUse[pin] = sghGC.PULTRA
                       
                                      
                    #end of normal pin checking

                if self.dFind('pinpattern'):
                    #print 'Found pinpattern broadcast'
                    #print dataraw
                    #num_of_bits = PINS
                    outputall_pos = self.dataraw.find('pinpattern')
                    sensor_value = self.dataraw[(outputall_pos+10):].split()
                    print sensor_value
                    #sensor_value[0] = sensor_value[0][:-1]                    
                    print sensor_value[0]
                    bit_pattern = ('00000000000000000000000000'+sensor_value[0])[-sghGC.numOfPins:]
                    print 'bit_pattern %s' % bit_pattern
                    j = 0
                    for pin in range(sghGC.numOfPins):
                        bit_state = ((2**pin) & sensor_value[0]) >> pin
                        print 'dummy pin %d state %d' % (pin, bit_state)
                        if (sghGC.pinUse[pin] == sghGC.POUTPUT):
                            if bit_pattern[-(j+1)] == '0':
                                sghGC.pinUpdate(pin,0)
                            else:
                                sghGC.pinUpdate(pin,0)
                            j = j + 1
                             

                if ('steppera' in dataraw) or ('turna' in dataraw):
                    if (stepperInUse[STEPPERA] == False):
                        print "StepperA Stasrting"
                        steppera = StepperControl(11,12,13,15,step_delay)
                        steppera.start()
                        stepperInUse[STEPPERA] = True
                        turnAStep = 0
                        steppera.changeSpeed(max(-100,min(100,int(float(0)))),2123456789)
                    else:
                        steppera.changeSpeed(max(-100,min(100,int(float(0)))),2123456789)
                        

                if ('stepperb' in dataraw):
                    if (stepperInUse[STEPPERB] == False):
                        print "StepperB Stasrting"
                        stepperb = StepperControl(16,18,22,7,step_delay)
                        stepperb.start()
                        stepperInUse[STEPPERB] = True
                        turnBStep = 0
                        stepperb.changeSpeed(max(-100,min(100,int(float(0)))),2123456789)
                    else:
                        stepperb.changeSpeed(max(-100,min(100,int(float(0)))),2123456789)
                        
                if ('stepperc' in dataraw):
                    if (stepperInUse[STEPPERC] == False):
                        print "StepperC Stasrting"
                        stepperc = StepperControl(24,26,19,21,step_delay)
                        stepperc.start()
                        stepperInUse[STEPPERC] = True
                        turnCStep = 0 #reset turn variale
                        stepperc.changeSpeed(max(-100,min(100,int(float(0)))),2123456789)
                    else:
                        stepperc.changeSpeed(max(-100,min(100,int(float(0)))),2123456789)


                if  '1coil' in dataraw:
                    print "1coil broadcast"
                    stepType = 0
                    print "step mode" ,stepMode[stepType]
                    step_delay = 0.0025

                if  '2coil' in dataraw:
                    print "2coil broadcast"
                    stepType = 1
                    print "step mode" ,stepMode[stepType]
                    step_delay = 0.0025
                    
                if  'halfstep' in dataraw:
                    print "halfstep broadcast"
                    stepType = 2
                    print "step mode" ,stepMode[stepType]
                    step_delay = 0.0013
                    
                if "version" in dataraw:
                    bcast_str = 'sensor-update "%s" %d' % ("Version", int(Version * 1000))
                    #print 'sending: %s' % bcast_str
                    self.send_scratch_command(bcast_str)

                #end of broadcast check


            if 'stop handler' in dataraw:
                cleanup_threads((listener, sender))
                sys.exit()

            #else:
                #print 'received something: %s' % dataraw
###  End of  ScratchListner Class

def create_socket(host, port):
    while True:
        try:
            print 'Trying'
            scratch_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            scratch_sock.connect((host, port))
            break
        except socket.error:
            print "There was an error connecting to Scratch!"
            print "I couldn't find a Mesh session at host: %s, port: %s" % (host, port) 
            time.sleep(3)
            #sys.exit(1)

    return scratch_sock

def cleanup_threads(threads):
    for thread in threads:
        thread.stop()

    for thread in threads:
        thread.join()

    for pin in range(sghGC.numOfPins):
        if sghGC.pinUse[pin] == sghGC.PPWM:
            print "Stopping ", pin
            sghGC.pwmRef[pin].stop()
            print "Stopped ", pin
            
    if (stepperInUse[STEPPERA] == True):
        print "stopping stepperA"
        steppera.stop()
        print "stepperA stopped"
        
    if (stepperInUse[STEPPERB] == True):
        print "stopping stepperB"
        stepperb.stop()
        print "stepperB stopped"
            
    if (stepperInUse[STEPPERC] == True):
        print "stopping stepperC"
        stepperc.stop()
        print "stepperC stopped"

        
######### Main Program Here


#Set some constants and initialise lists

sghGC = sgh_GPIOController.GPIOController(True)
print sghGC.getPiRevision()

STEPPERA=0
STEPPERB=1
STEPPERC=2
stepperInUse = [False,False,False]
BIG_NUM = 2123456789

ADDON = ['Normal','Ladder','MotorPiTx','PiGlow','Compass','gPiO','Berry','pirocon'] #define addons
NUMOF_ADDON = len(ADDON) # find number of addons
ADDON_PRESENT = [False] * NUMOF_ADDON # create an enabled/disabled list
for i in range(NUMOF_ADDON): # set all addons to diabled
    ADDON_PRESENT[i] = False
    ADDON[i] = ADDON[i].lower()
    
turnAStep = 0
turnBStep = 0
turnCStep = 0
stepMode = ['1Coil','2Coil','HalfStep']
stepModeDelay = [0.0025,0.0025,0.0013]
stepType = 2
if stepType == 2:
    step_delay = 0.0013 # use smaller dealy fro halfstep mode
else:
    step_delay = 0.003

PORT = 42001
DEFAULT_HOST = '127.0.0.1'
BUFFER_SIZE = 240 #used to be 100
SOCKET_TIMEOUT = 1
firstRun = True




piglow = None
try:
    if sghGC.getPiRevision() == 1:
        print "Rev1 Board" 
        piglow = sgh_PiGlow.PiGlow(0)
        print piglow
    else:
        piglow = sgh_PiGlow.PiGlow(1)
    piglow.update_pwm_values()#PiGlow_Values)
except:
    print "No PiGlow Detected"
    
#See if Compass connected
compass = None
try:
    if sghGC.getPiRevision == 1:
        compass = Compass(gauss = 4.7, declination = (-0,0))
    else:
        compass = Compass(gauss = 4.7, declination = (-0,0))
    print "compass detected"
except:
    print "No Compass Detected"
    
pcaPWM = None
try:
    pcaPWM = PWM(0x40, debug=False)
    print pcaPWM
    print pcaPWM.setPWMFreq(60)                        # Set frequency to 60 Hz
    print "AdaFruit PCA9685 detected"
except:
    print "No pcaPwm Detected"
    
#If I2C then don't uses pins 3 and 5
if ((piglow != None) or (compass != None) or (pcaPWM != None)):
    print "I2C device detected"
    #pins = sghGC.PIN_NUM
else:
    print "No I2C Device Detected"
    #PIN_NUM = sghGC.PIN_NUM

 
ULTRA_IN_USE = [False] * sghGC.numOfPins
ultraTotalInUse = 0
ultraSleep = 1.0


if __name__ == '__main__':
    if len(sys.argv) > 1:
        host = sys.argv[1]
    else:
        host = DEFAULT_HOST
    host = host.replace("'", "")

cycle_trace = 'start'


sghGC.setPinMode()

while True:

    if (cycle_trace == 'disconnected'):
        print "Scratch disconnected"
        cleanup_threads((listener, sender))
        sghGC.stopServod()
        time.sleep(1)
        cycle_trace = 'start'

    if (cycle_trace == 'start'):
        # open the socket
        print 'Starting to connect...' ,
        the_socket = create_socket(host, PORT)
        print 'Connected!'
        the_socket.settimeout(SOCKET_TIMEOUT)
        listener = ScratchListener(the_socket)
#        steppera = StepperControl(11,12,13,15,step_delay)
#        stepperb = StepperControl(16,18,22,7,step_delay)
#        stepperc = StepperControl(24,26,19,21,step_delay)


##        data = the_socket.recv(BUFFER_SIZE)
##        print "Discard 1st data buffer" , data[4:].lower()
        sender = ScratchSender(the_socket)
        cycle_trace = 'running'
        print "Running...."
        listener.start()
        sender.start()
##        stepperb.start()


    # wait for ctrl+c
    try:
#        val = values.pop(0)
#        values.append(val)
#        # update the piglow with current values
#        piglow.update_pwm_values(values)

        time.sleep(0.1)
    except KeyboardInterrupt:
        cleanup_threads((listener,sender))
        sghGC.stopServod()
        sghGC.cleanup()
        sys.exit()
        print "CleanUp complete"
        
#### End of main program

        

