# This code is copyright Simon Walters under GPL v2
# This code is derived from Pi-Face scratch_handler by Thomas Preston
# This code now hosted on Github thanks to Ben Nuttall
# Version 2.32 22Jun13



from array import *
import threading
import socket
import time
import sys
import struct
import datetime as dt

import RPi.GPIO as GPIO
GPIO.setmode(GPIO.BOARD)
GPIO.setwarnings(False)
GPIO.cleanup()

#Set some constants and initialise arrays
STEPPERA=0
STEPPERB=1
STEPPERC=2
stepperInUse = array('b',[False,False,False])
INVERT = False
BIG_NUM = 2123456789

ADDON = ['LadderBoard'] #define addons
NUMOF_ADDON = len(ADDON) # find number of addons
ADDON_PRESENT = [int] * NUMOF_ADDON # create an enabled/disabled array
for i in range(NUMOF_ADDON): # set all addons to diabled
    ADDON_PRESENT[i] = 0
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


PIN_NUM = array('i',[11,12,13,15,16,18,22, 7, 3, 5,24,26,19,21,23, 8,10])
PIN_USE = array('i',[ 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0])
#  GPIO_NUM = array('i',[17,18,21,22,23,24,25,4,14,15,8,7,10,9])
PINS = len(PIN_NUM)
PIN_NUM_LOOKUP=[int] * 27


PWM_OUT = [None] * PINS

def isNumeric(s):
    try:
        float(s)
        return True
    except ValueError:
        return False


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
        self.pins = array("i",[PIN_NUM_LOOKUP[pinA],PIN_NUM_LOOKUP[pinB],PIN_NUM_LOOKUP[pinC],PIN_NUM_LOOKUP[pinD]])
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
            


    def physical_pin_update(self, pin_index, value):
        if (PIN_USE[pin_index] == 0):
            PIN_USE[pin_index] = 1
            GPIO.setup(PIN_NUM[pin_index],GPIO.OUT)
            print 'pin' , PIN_NUM[pin_index] , ' changed to digital out from input'
        if (PIN_USE[pin_index] == 2):
            PIN_USE[pin_index] = 1
            PWM_OUT[pin_index].stop()
            GPIO.setup(PIN_NUM[pin_index],GPIO.OUT)
            print 'pin' , PIN_NUM[pin_index] , ' changed to digital out from PWM'
        if (PIN_USE[pin_index] == 1):
            #print 'setting physical pin %d to %d' % (PIN_NUM[pin_index],value)
            GPIO.output(PIN_NUM[pin_index], value)


    def step_coarse(self,a,b,c,d,delay):
        global stepType
        lstepMode = stepMode[stepType]
        #print stepMode[stepType]
        if lstepMode == '1Coil':
            self.physical_pin_update(d,0)
            self.physical_pin_update(a,1)
            time.sleep(delay)

            
            self.physical_pin_update(b,1)
            self.physical_pin_update(a,0)
            time.sleep(delay)
            
            
            self.physical_pin_update(c,1)
            self.physical_pin_update(b,0)
            time.sleep(delay)
            
            
            self.physical_pin_update(d,1)
            self.physical_pin_update(c,0)
            time.sleep(delay)
            
        elif lstepMode == '2Coil':
            self.physical_pin_update(d,0)
            self.physical_pin_update(c,0)
            self.physical_pin_update(a,1)
            self.physical_pin_update(b,1)

            time.sleep(delay)

            self.physical_pin_update(a,0)
            self.physical_pin_update(c,1)
            time.sleep(delay)
            
            self.physical_pin_update(b,0)
            self.physical_pin_update(d,1)
            time.sleep(delay)
            
            self.physical_pin_update(c,0)
            self.physical_pin_update(a,1)
            time.sleep(delay)
            
        elif lstepMode == 'HalfStep':
            self.physical_pin_update(d,0) 
            self.physical_pin_update(a,1)
            time.sleep(delay)


            self.physical_pin_update(b,1)
            time.sleep(delay)

            self.physical_pin_update(a,0)
            time.sleep(delay)
            
            self.physical_pin_update(c,1)
            time.sleep(delay)

            self.physical_pin_update(b,0)
            time.sleep(delay)

            self.physical_pin_update(d,1)
            time.sleep(delay)

            self.physical_pin_update(c,0)
            time.sleep(delay)
            
            self.physical_pin_update(a,1)
            time.sleep(delay)

    def pause(self):
        self.physical_pin_update(self.pins[0],0)
        self.physical_pin_update(self.pins[1],0)
        self.physical_pin_update(self.pins[2],0)
        self.physical_pin_update(self.pins[3],0)
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
                    
class PiZyPwm(threading.Thread):

  def __init__(self, frequency, gpioPin, gpioScheme):
     """
Init the PiZyPwm instance. Expected parameters are :
- frequency : the frequency in Hz for the PWM pattern. A correct value may be 100.
- gpioPin : the pin number which will act as PWM ouput
- gpioScheme : the GPIO naming scheme (see RPi.GPIO documentation)
"""
     self.baseTime = 1.0 / frequency
     self.maxCycle = 100.0
     self.sliceTime = self.baseTime / self.maxCycle
     self.gpioPin = gpioPin
     self.terminated = False
     self.toTerminate = False
     GPIO.setmode(gpioScheme)


  def start(self, dutyCycle):
    """
Start PWM output. Expected parameter is :
- dutyCycle : percentage of a single pattern to set HIGH output on the GPIO pin
Example : with a frequency of 1 Hz, and a duty cycle set to 25, GPIO pin will
stay HIGH for 1*(25/100) seconds on HIGH output, and 1*(75/100) seconds on LOW output.
"""
    self.dutyCycle = dutyCycle
    GPIO.setup(self.gpioPin, GPIO.OUT)
    self.thread = threading.Thread(None, self.run, None, (), {})
    self.thread.start()


  def run(self):
    """
Run the PWM pattern into a background thread. This function should not be called outside of this class.
"""
    while self.toTerminate == False:
      if self.dutyCycle > 0:
        GPIO.output(self.gpioPin, GPIO.HIGH)
        time.sleep(self.dutyCycle * self.sliceTime)
      
      if self.dutyCycle < self.maxCycle:
        GPIO.output(self.gpioPin, GPIO.LOW)
        time.sleep((self.maxCycle - self.dutyCycle) * self.sliceTime)

    self.terminated = True


  def changeDutyCycle(self, dutyCycle):
    """
Change the duration of HIGH output of the pattern. Expected parameter is :
- dutyCycle : percentage of a single pattern to set HIGH output on the GPIO pin
Example : with a frequency of 1 Hz, and a duty cycle set to 25, GPIO pin will
stay HIGH for 1*(25/100) seconds on HIGH output, and 1*(75/100) seconds on LOW output.
"""
    self.dutyCycle = dutyCycle


  def changeFrequency(self, frequency):
    """
Change the frequency of the PWM pattern. Expected parameter is :
- frequency : the frequency in Hz for the PWM pattern. A correct value may be 100.
Example : with a frequency of 1 Hz, and a duty cycle set to 25, GPIO pin will
stay HIGH for 1*(25/100) seconds on HIGH output, and 1*(75/100) seconds on LOW output.
"""
    self.baseTime = 1.0 / frequency
    self.sliceTime = self.baseTime / self.maxCycle


  def stop(self):
    """
Stops PWM output.
"""
    self.toTerminate = True
    while self.terminated == False:
      # Just wait
      time.sleep(0.01)
  
    GPIO.output(self.gpioPin, GPIO.LOW)
    GPIO.setup(self.gpioPin, GPIO.IN)


'''
from Tkinter import Tk
from tkSimpleDialog import askstring
root = Tk()
root.withdraw()
'''




#Procedure to set pin mode for each pin
def SetPinMode():
    for i in range(PINS):
        if (PIN_USE[i] == 1):
            GPIO.setup(PIN_NUM[i],GPIO.OUT)
            print 'pin' , PIN_NUM[i] , ' out'
        else:
            GPIO.setup(PIN_NUM[i],GPIO.IN,pull_up_down=GPIO.PUD_UP)
            print 'pin' , PIN_NUM[i] , ' in'
        PIN_NUM_LOOKUP[PIN_NUM[i]] = i










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


    def stop(self):
        self._stop.set()

    def stopped(self):
        return self._stop.isSet()

    def run(self):
        last_bit_pattern=0L
        for i in range(PINS):
            #print 'i %d' % i
            #print 'GPIO PIN %d' % GPIO_PIN_INPUT[i]
            if (PIN_USE[i] == 0):
                last_bit_pattern += GPIO.input(PIN_NUM[i]) << i
            #else:
                #last_bit_pattern += 1 << i
            #print 'lbp %s' % bin(last_bit_pattern)

        last_bit_pattern = last_bit_pattern ^ -1

        
        while not self.stopped():
            time.sleep(0.01) # be kind to cpu - not certain why :)
            pin_bit_pattern = 0L
            for i in range(PINS):
                if (PIN_USE[i] == 0):
                    #print 'pin' , PIN_NUM[i] , GPIO.input(PIN_NUM[i]
                    pin_bit_pattern += GPIO.input(PIN_NUM[i]) << i
                #else:
                    #pin_bit_pattern += 1 << i
            #print bin(pin_bit_pattern)
            # if there is a change in the input pins
            changed_pins = pin_bit_pattern ^ last_bit_pattern
            #print "changed pins" , bin(changed_pins)
            if changed_pins:
                #print 'pin bit pattern %d' % pin_bit_pattern

                try:
                    self.broadcast_changed_pins(changed_pins, pin_bit_pattern)
                except Exception as e:
                    print e
                    break

            last_bit_pattern = pin_bit_pattern

##            sensor_name = "turninga"
##            value = 100.0
##            bcast_str = 'sensor-update "%s" %d' % (sensor_name, value)
##            print 'sending: %s' % bcast_str
##            self.send_scratch_command(bcast_str)
            

    def broadcast_changed_pins(self, changed_pin_map, pin_value_map):
        for i in range(PINS):
            # if we care about this pin's value
            if (changed_pin_map >> i) & 0b1:
                pin_value = (pin_value_map >> i) & 0b1
                if (PIN_USE[i] == 0):
                    #print PIN_NUM[i] , pin_value
                    self.broadcast_pin_update(i, pin_value)
                    

    def broadcast_pin_update(self, pin_index, value):
        #sensor_name = "gpio" + str(GPIO_NUM[pin_index])
        #bcast_str = 'sensor-update "%s" %d' % (sensor_name, value)
        #print 'sending: %s' % bcast_str
        #self.send_scratch_command(bcast_str)
        if ADDON_PRESENT[0] == 1:
            #do ladderboard stuff
            switch_array = array('i',[3,4,2,1])
            #switch_lookup = array('i',[24,26,19,21])
            sensor_name = "switch" + str(switch_array[pin_index-10])
        else:
            sensor_name = "pin" + str(PIN_NUM[pin_index])
        bcast_str = 'sensor-update "%s" %d' % (sensor_name, value)
        #print 'sending: %s' % bcast_str
        self.send_scratch_command(bcast_str)

    def send_scratch_command(self, cmd):
        n = len(cmd)
        a = array('c')
        a.append(chr((n >> 24) & 0xFF))
        a.append(chr((n >> 16) & 0xFF))
        a.append(chr((n >>  8) & 0xFF))
        a.append(chr(n & 0xFF))
        self.scratch_socket.send(a.tostring() + cmd)


class ScratchListener(threading.Thread):
    def __init__(self, socket):
        threading.Thread.__init__(self)
        self.scratch_socket = socket
        self._stop = threading.Event()
        
    def send_scratch_command(self, cmd):
        n = len(cmd)
        a = array('c')
        a.append(chr((n >> 24) & 0xFF))
        a.append(chr((n >> 16) & 0xFF))
        a.append(chr((n >>  8) & 0xFF))
        a.append(chr(n & 0xFF))
        self.scratch_socket.send(a.tostring() + cmd)


    def stop(self):
        self._stop.set()

    def stopped(self):
        return self._stop.isSet()

    def physical_pin_update(self, pin_index, value):
        if INVERT == True:
            if PIN_USE[pin_index] == 1:
                value = abs(value - 1)
        if (PIN_USE[pin_index] == 0):
            PIN_USE[pin_index] = 1
            GPIO.setup(PIN_NUM[pin_index],GPIO.OUT)
            print 'pin' , PIN_NUM[pin_index] , ' changed to digital out from input'
        if (PIN_USE[pin_index] == 2):
            PIN_USE[pin_index] = 1
            PWM_OUT[pin_index].stop()
            GPIO.setup(PIN_NUM[pin_index],GPIO.OUT)
            print 'pin' , PIN_NUM[pin_index] , ' changed to digital out from PWM'
        if (PIN_USE[pin_index] == 1):
            #print 'setting gpio %d (physical pin %d) to %d' % (GPIO_NUM[pin_index],PIN_NUM[pin_index],value)
            GPIO.output(PIN_NUM[pin_index], value)

    def step_coarse(self,a,b,c,d,delay):
        self.physical_pin_update(a,1)
        self.physical_pin_update(d,0)
        time.sleep(delay)

        self.physical_pin_update(b,1)
        self.physical_pin_update(a,0)
        time.sleep(delay)
        
        self.physical_pin_update(c,1)
        self.physical_pin_update(b,0)
        time.sleep(delay)
        
        self.physical_pin_update(d,1)
        self.physical_pin_update(c,0)
        time.sleep(delay)

    def run(self):
        global cycle_trace,turnAStep,turnBStep,turnCStep,step_delay,stepType,INVERT,steppera,stepperb,stepperc

        firstRun = False #Used for testing in overcoming Scratch "bug/feature"
        #This is main listening routine
        while not self.stopped():
            try:
                data = self.scratch_socket.recv(BUFFER_SIZE) # get the data from the socket
                dataraw = data[4:].lower() # convert all to lowercase
                #print 'data revd from scratch-Length: %d, Data: %s' % (len(dataraw), dataraw)
                #print 'Cycle trace' , cycle_trace
                if len(dataraw) == 0:
                    #This is probably due to client disconnecting
                    #I'd like the program to retry connecting to the client
                    #tell outer loop that Scratch has disconnected
                    if cycle_trace == 'running':
                        cycle_trace = 'disconnected'
                        break

            except socket.timeout:
                #print "No data received: socket timeout"
                continue
            
            #This section is only enabled if flag set - I am in 2 minds as to whether to use it or not!
            if firstRun == True:
                if 'sensor-update' in dataraw:
                    #print "this data ignored" , dataraw
                    dataraw = ''
                    firstRun = False

            #If outputs need globally inverting (7 segment common anode needs it)
            if ('invert' in dataraw):
                INVERT = True
                
            #Change pins from input to output if more needed
            if ('config' in dataraw):
                for i in range(PINS):
                    #check_broadcast = str(i) + 'on'
                    #print check_broadcast
                    physical_pin = PIN_NUM[i]
                    if 'config' + str(physical_pin)+'out' in dataraw: # change pin to output from input
                        if PIN_USE[i] == 0:                           # check to see if it is an input at moment
                            GPIO.setup(PIN_NUM[i],GPIO.OUT)           # make it an output
                            print 'pin' , PIN_NUM[i] , ' out'
                            PIN_USE[i] = 1
                    if 'config' + str(physical_pin)+'in' in dataraw:                # change pin to input from output
                        if PIN_USE[i] != 0:                                         # check to see if it not an input already
                            GPIO.setup(PIN_NUM[i],GPIO.IN,pull_up_down=GPIO.PUD_UP) # make it an input
                            print 'pin' , PIN_NUM[i] , ' in'
                            PIN_USE[i] = 0



            #Listen for Variable changes
            if 'sensor-update' in dataraw:
                #print "sensor-update rcvd" , dataraw
              
                if ADDON_PRESENT[0] == 1:
                    #do ladderboard stuff

                    if (('allleds" 1' in dataraw) or ('allleds" "on' in dataraw) or ('allleds" "high' in dataraw)):
                        for i in range(0, 10): # limit pins to first 10
                            self.physical_pin_update(i,1)
                    if (('allleds" 0' in dataraw) or ('allleds" "off' in dataraw) or ('allleds" "low' in dataraw)):
                        for i in range(0, 10): # limit pins to first 10
                            self.physical_pin_update(i,0)
                    
                    for i in range(0, 10): # limit pins to first 10
                        physical_pin = PIN_NUM[i]
                        pin_string = 'led' + str(i + 1)
                        #print "pin string" , pin_string
                        if (((pin_string + '" 1' )in dataraw) or ((pin_string + '" "on') in dataraw) or ((pin_string + '" "high') in dataraw )):
                            #print "variable detect 1/on/high" , dataraw
                            self.physical_pin_update(i,1)
                        if  (((pin_string + '" 0') in dataraw) or ((pin_string + '" "off') in dataraw) or ((pin_string + '" "low') in dataraw )):
                            #print "variable detect 0/off/low" , dataraw
                            self.physical_pin_update(i,0)

                        #check for power variable commands
                        if  'power' + str(i + 1) in dataraw:
                            outputall_pos = dataraw.find('power' + str(i + 1))
                            sensor_value = dataraw[(outputall_pos+1+len('power' + str(i + 1))):].split()
                            #print 'power', str(physical_pin) , sensor_value[0]

                            if isNumeric(sensor_value[0]):
                                if PIN_USE[i] != 2:
                                    PIN_USE[i] = 2
                                    PWM_OUT[i] = PiZyPwm(100, PIN_NUM[i], GPIO.BOARD)
                                    PWM_OUT[i].start(max(0,min(100,int(sensor_value[0]))))
                                else:
                                    PWM_OUT[i].changeDutyCycle(max(0,min(100,int(sensor_value[0]))))
                                    
                else:   #normal variable processing with no add on board
                    #gloablly set all ports
                    if (('allpins" 1' in dataraw) or ('allpins" "on' in dataraw) or ('allpins" "high' in dataraw)):
                        for i in range(PINS): 
                            self.physical_pin_update(i,1)
                    if (('allpins" 0' in dataraw) or ('allpins" "off' in dataraw) or ('allpins" "low' in dataraw)):
                        for i in range(PINS): 
                            self.physical_pin_update(i,0)
                    
                    #check for individual pin on off commands
                    for i in range(PINS):
                        #check_broadcast = str(i) + 'on'
                        #print check_broadcast
                        physical_pin = PIN_NUM[i]
                        pin_string = 'pin' + str(physical_pin)
                        #print "pin string" , pin_string
                        if (((pin_string + '" 1' )in dataraw) or ((pin_string + '" "on') in dataraw) or ((pin_string + '" "high') in dataraw )):
                            #print "variable detect 1/on/high" , dataraw
                            self.physical_pin_update(i,1)
                        if  (((pin_string + '" 0') in dataraw) or ((pin_string + '" "off') in dataraw) or ((pin_string + '" "low') in dataraw )):
                            #print "variable detect 0/off/low" , dataraw
                            self.physical_pin_update(i,0)

                        #check for power variable commands
                        if  'power' + str(physical_pin) in dataraw:
                            outputall_pos = dataraw.find('power' + str(physical_pin))
                            sensor_value = dataraw[(outputall_pos+1+len('power' + str(physical_pin))):].split()
                            #print 'power', str(physical_pin) , sensor_value[0]

                            if isNumeric(sensor_value[0]):
                                if PIN_USE[i] != 2:
                                    PIN_USE[i] = 2
                                    PWM_OUT[i] = PiZyPwm(100, PIN_NUM[i], GPIO.BOARD)
                                    PWM_OUT[i].start(max(0,min(100,int(sensor_value[0]))))
                                else:
                                    PWM_OUT[i].changeDutyCycle(max(0,min(100,int(sensor_value[0]))))
                                    
                        if  'motor' + str(physical_pin) in dataraw:
                            outputall_pos = dataraw.find('motor' + str(physical_pin))
                            sensor_value = dataraw[(outputall_pos+1+len('motor' + str(physical_pin))):].split()
                            #print 'motor', str(physical_pin) , sensor_value[0]

                            if isNumeric(sensor_value[0]):
                                if PIN_USE[i] != 2:
                                    PIN_USE[i] = 2
                                    PWM_OUT[i] = PiZyPwm(100, PIN_NUM[i], GPIO.BOARD)
                                    PWM_OUT[i].start(max(0,min(100,int(sensor_value[0]))))
                                else:
                                    PWM_OUT[i].changeDutyCycle(max(0,min(100,int(sensor_value[0]))))



                #Use bit pattern to control ports
                if 'pinpattern' in dataraw:
                    #print 'Found pinpattern'
                    num_of_bits = PINS
                    outputall_pos = dataraw.find('pinpattern')
                    sensor_value = dataraw[(outputall_pos+12):].split()
                    #print sensor_value[0]
                    bit_pattern = ('00000000000000000000000000'+sensor_value[0])[-num_of_bits:]
                    #print 'bit_pattern %s' % bit_pattern
                    j = 0
                    for i in range(PINS):
                    #bit_state = ((2**i) & sensor_value) >> i
                    #print 'dummy pin %d state %d' % (i, bit_state)
                        if (PIN_USE[i] == 1):
                            if bit_pattern[-(j+1)] == '0':
                                self.physical_pin_update(i,0)
                            else:
                                self.physical_pin_update(i,1)
                            j = j + 1

                                       
                if  'motora' in dataraw:
                    #print "MotorA Received"
                    #print "stepper status" , stepperInUse[STEPPERA]
                    if (stepperInUse[STEPPERA] == True):
                        #print "Stepper A in operation"
                        outputall_pos = dataraw.find('motora')
                        sensor_value = dataraw[(outputall_pos+1+len('motora')):].split()
                        #print 'steppera', sensor_value[0]

                        if isNumeric(sensor_value[0]):
                            #print "send change to motora as a stepper" , sensor_value[0]
                            steppera.changeSpeed(max(-100,min(100,int(float(sensor_value[0])))),2123456789)
                        
                    else:
                        for i in range(PINS):
                            if PIN_NUM[i] == 11:
                                #print "Mapping MotorA to Pin11"
                                #print dataraw
                                outputall_pos = dataraw.find('motora')
                                sensor_value = dataraw[(outputall_pos+1+len('motora')):].split()
                                #print 'motorb', sensor_value[0]

                                if isNumeric(sensor_value[0]):
                                    if PIN_USE[i] != 2:
                                        print "setting pin", PIN_NUM[i] , "to PWM" 
                                        PIN_USE[i] = 2
                                        PWM_OUT[i] = PiZyPwm(100, PIN_NUM[i], GPIO.BOARD)
                                        PWM_OUT[i].start(max(0,min(100,int(sensor_value[0]))))
                                    else:
                                        PWM_OUT[i].changeDutyCycle(max(0,min(100,int(float(sensor_value[0])))))

                if  'motorb' in dataraw:
                    if (stepperInUse[STEPPERB] == True):
                        outputall_pos = dataraw.find('motorb')
                        sensor_value = dataraw[(outputall_pos+1+len('motorb')):].split()
                        #print 'stepperb', sensor_value[0]

                        if isNumeric(sensor_value[0]):

                            #print "send change to motorb as a stepper" , sensor_value[0]
                            #print type(sensor_value[0])
                            #print "***"+sensor_value[0]+"***"
                            #print type(float(sensor_value[0]))
                            #print float(sensor_value[0])
                            stepperb.changeSpeed(max(-100,min(100,int(float(sensor_value[0])))),2123456789)
                        
                    else:
                        for i in range(PINS):
                            if PIN_NUM[i] == 12:
                                #print dataraw
                                outputall_pos = dataraw.find('motorb')
                                sensor_value = dataraw[(outputall_pos+1+len('motorb')):].split()
                                #print 'motorb', sensor_value[0]

                                if isNumeric(sensor_value[0]):
                                    if PIN_USE[i] != 2:
                                        print "setting pin", PIN_NUM[i] , "to PWM" 
                                        PIN_USE[i] = 2
                                        PWM_OUT[i] = PiZyPwm(100, PIN_NUM[i], GPIO.BOARD)
                                        PWM_OUT[i].start(max(0,min(100,int(sensor_value[0]))))
                                    else:
                                        PWM_OUT[i].changeDutyCycle(max(0,min(100,int(float(sensor_value[0])))))

                if  'motorc' in dataraw:
                    if (stepperInUse[STEPPERC] == True):
                        outputall_pos = dataraw.find('motorc')
                        sensor_value = dataraw[(outputall_pos+1+len('motorc')):].split()
                        print 'stepperc', sensor_value[0]

                        if isNumeric(sensor_value[0]):

                            #print "send change to motorb as a stepper" , sensor_value[0]
                            #print type(sensor_value[0])
                            #print "***"+sensor_value[0]+"***"
                            #print type(float(sensor_value[0]))
                            #print float(sensor_value[0])
                            stepperc.changeSpeed(max(-100,min(100,int(float(sensor_value[0])))),2123456789)
                        
                    else:
                        for i in range(PINS):
                            if PIN_NUM[i] == 13:
                                #print dataraw
                                outputall_pos = dataraw.find('motorc')
                                sensor_value = dataraw[(outputall_pos+1+len('motorc')):].split()
                                #print 'motorb', sensor_value[0]

                                if isNumeric(sensor_value[0]):
                                    if PIN_USE[i] != 2:
                                        print "setting pin", PIN_NUM[i] , "to PWM" 
                                        PIN_USE[i] = 2
                                        PWM_OUT[i] = PiZyPwm(100, PIN_NUM[i], GPIO.BOARD)
                                        PWM_OUT[i].start(max(0,min(100,int(sensor_value[0]))))
                                    else:
                                        PWM_OUT[i].changeDutyCycle(max(0,min(100,int(float(sensor_value[0])))))



                if  'stepdelay' in dataraw:
                    sensor_value = dataraw[(dataraw.find('stepdelay')+1+len('stepdelay')):].split()
                    print 'step delay changed to', sensor_value[0]
                    if isNumeric(sensor_value[0]):
                        step_delay = float(sensor_value[0])


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


                        

            if 'broadcast' in dataraw:
                #print 'broadcast in data:' , dataraw

                for i in range(NUMOF_ADDON):
                    if ADDON[i] in dataraw:
                        ADDON_PRESENT[i] = 1
                        if ADDON[i] == "ladderboard":
                            for k in range(0,10):
                                PIN_USE[k] = 1
                            for k in range(10,14):
                                PIN_USE[k] = 0
                            SetPinMode()

                            for k in range(1,5):
                                sensor_name = 'switch' + str(k)
                                bcast_str = 'sensor-update "%s" %d' % (sensor_name, 1)
                                #print 'sending: %s' % bcast_str
                                self.send_scratch_command(bcast_str)

   

                if ADDON_PRESENT[0] == 1: # Gordon's Ladder Board

                    if (('allon' in dataraw) or ('allhigh' in dataraw)):
                        for i in range(0, 10):
                            if (PIN_USE[i] <> 0):
                                self.physical_pin_update(i,1)
                    if (('alloff' in dataraw) or ('alllow' in dataraw)):
                        for i in range(0, 10):
                            if (PIN_USE[i] <> 0):
                                self.physical_pin_update(i,0)
                                
                        #do ladderboard stuff
                    for i in range(0, 10):
                        #print i
                        physical_pin = PIN_NUM[i]
                        #print "pin" + str(i + 1) + "high"
                        if (('led' + str(i + 1)+'high' in dataraw) or ('led' + str(i + 1)+'on' in dataraw)):
                            #print dataraw
                            self.physical_pin_update(i,1)

                        if (('led' + str(i + 1)+'low' in dataraw) or ('led' + str(i + 1)+'off' in dataraw)):
                            #print dataraw
                            self.physical_pin_update(i,0)

                else:

                    if (('allon' in dataraw) or ('allhigh' in dataraw)):
                        for i in range(PINS):
                            if (PIN_USE[i] <> 0):
                                self.physical_pin_update(i,1)
                    if (('alloff' in dataraw) or ('alllow' in dataraw)):
                        for i in range(PINS):
                            if (PIN_USE[i] <> 0):
                                self.physical_pin_update(i,0)
                                
                    #check pins
                    for i in range(PINS):
                        #check_broadcast = str(i) + 'on'
                        #print check_broadcast
                        physical_pin = PIN_NUM[i]
                        if (('pin' + str(physical_pin)+'high' in dataraw) or ('pin' + str(physical_pin)+'on' in dataraw)):
                            #print dataraw
                            self.physical_pin_update(i,1)

                        if (('pin' + str(physical_pin)+'low' in dataraw) or ('pin' + str(physical_pin)+'off' in dataraw)):
                            #print dataraw
                            self.physical_pin_update(i,0)

                        if ('sonar' + str(physical_pin)) in dataraw:
                            self.physical_pin_update(i,1)
                            ti = time.time()
                            # setup a array to hold 3 values and then do 3 distance calcs and store them
                            #print 'sonar started'
                            distarray = array('f',[0.0,0.0,0.0])
                            ts=time.time()
                            print
                            for k in range(3):
                                #print "sonar pulse" , k
                                #GPIO.setup(physical_pin,GPIO.OUT)
                                #print physical_pin , i
                                GPIO.output(physical_pin, 1)    # Send Pulse high
                                time.sleep(0.00001)     #  wait
                                GPIO.output(physical_pin, 0)  #  bring it back low - pulse over.
                                t0=time.time() # remember current time
                                GPIO.setup(physical_pin,GPIO.IN)
                                #PIN_USE[i] = 0 don't bother telling system
                                
                                t1=t0
                                # This while loop waits for input pin (7) to be low but with a 0.04sec timeout 
                                while ((GPIO.input(physical_pin)==0) and ((t1-t0) < 0.02)):
                                    #time.sleep(0.00001)
                                    t1=time.time()
                                t1=time.time()
                                #print 'low' , (t1-t0).microseconds
                                t2=t1
                                #  This while loops waits for input pin to go high to indicate pulse detection
                                #  with 0.04 sec timeout
                                while ((GPIO.input(physical_pin)==1) and ((t2-t1) < 0.02)):
                                    #time.sleep(0.00001)
                                    t2=time.time()
                                t2=time.time()
                                #print 'high' , (t2-t1).microseconds
                                t3=(t2-t1)  # t2 contains time taken for pulse to return
                                print "total time " , t3
                                distance=t3*343/2*100  # calc distance in cm
                                distarray[k]=distance
                                print distance
                                GPIO.setup(physical_pin,GPIO.OUT)
                            tf = time.time() - ts
                            distance = sorted(distarray)[1] # sort the array and pick middle value as best distance
                            
                            #print "total time " , tf
                            #for k in range(5):
                                #print distarray[k]
                            #print "pulse time" , distance*58
                            #print "total time in microsecs" , (tf-ti).microseconds                    
                            # only update Scratch values if distance is < 500cm
                            if (distance > 280):
                                distance = 299
                            if (distance < 2):
                                distance = 1

                            #print'Distance:',distance,'cm'
                            sensor_name = 'sonar' + str(physical_pin)
                            bcast_str = 'sensor-update "%s" %d' % (sensor_name, distance)
                            #print 'sending: %s' % bcast_str
                            self.send_scratch_command(bcast_str)
                    #end of normal pin checking

                if 'pinpattern' in dataraw:
                    #print 'Found pinpattern broadcast'
                    #print dataraw
                    num_of_bits = PINS
                    outputall_pos = dataraw.find('pinpattern')
                    sensor_value = dataraw[(outputall_pos+10):].split()
                    sensor_value[0] = sensor_value[0][:-1]                    
                    #print sensor_value[0]
                    bit_pattern = ('00000000000000000000000000'+sensor_value[0])[-num_of_bits:]
                    #print 'bit_pattern %s' % bit_pattern
                    j = 0
                    for i in range(PINS):
                    #bit_state = ((2**i) & sensor_value) >> i
                    #print 'dummy pin %d state %d' % (i, bit_state)
                        if (PIN_USE[i] == 1):
                            if bit_pattern[-(j+1)] == '0':
                                self.physical_pin_update(i,0)
                            else:
                                self.physical_pin_update(i,1)
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

                #end of broadcast check
                

            if 'stop handler' in dataraw:
                cleanup_threads((listener, sender))
                sys.exit()

            #else:
                #print 'received something: %s' % dataraw


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

    for i in range(PINS):
        if PIN_USE[i] == 2:
            print "Stopping ", PIN_NUM[i]
            PWM_OUT[i].stop()
            print "Stopped ", PIN_NUM[i]

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

if __name__ == '__main__':
    if len(sys.argv) > 1:
        host = sys.argv[1]
    else:
        host = DEFAULT_HOST

cycle_trace = 'start'


SetPinMode()


while True:

    if (cycle_trace == 'disconnected'):
        print "Scratch disconnected"
        cleanup_threads((listener, sender))
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
        time.sleep(0.1)
    except KeyboardInterrupt:
        cleanup_threads((listener,sender))
        sys.exit()

