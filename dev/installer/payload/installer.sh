#!/bin/bash
#V A add in chmod scratch_gpio.sh
#Version B � go back to installing deb gpio package directly
#Version C � install sb files into /home/pi/Documents/Scratch Projects
#Version D � create �/home/pi/Documents/Scratch Projects� if it doesn�t exist
#Version E � change permissions on �/home/pi/Documents/Scratch Projects�
#Version F 13Oct12 � rem out rpi.gpio as now included in Raspbian
#Version G 20Mar13 - Allow otheruser option on commandline (Tnever/meltwater)
#Version H 24Mar13 - correct newline issues
#Version 29Oct13 Add in Chown commands and extra Adafruit and servod files and alter gpio_scrath2.sh and bit of chmod +x make V3
f_exit(){
echo ""
echo "Usage:"
echo "i.e. sudo install_scratchgpio3.sh otheruser"
echo "Optional: Add a non-default 'otheruser' username after the command (default is:pi)."
exit
}
echo "Debug Info"

#echo $SUDO_USER

echo "Running Installer"
if [ -z $1 ]
then
HDIR="/home/pi"
USERID="pi"
GROUPID="pi"
else
HDIR=/home/$1
USERID=`id -n -u $1`
GROUPID=`id -n -g $1`
fi

#Confirm if install should continue with default PI user or inform about commandline option.
echo ""
echo "Install Details:"
echo "Home Directory: "$HDIR
echo "User: "$USERID
echo "Group: "$USERID
echo ""
if [ ! -d "$HDIR" ]; then
    echo ""; echo "The home directory does not exist!";f_exit;
fi
#echo "Is the above Home directory and User/Group correct (1/2)?"
#select yn in "Continue" "Cancel"; do
#    case $yn in
#        Continue ) break;;
#        Cancel ) f_exit;;
#    esac
#done

echo "Please wait a few seconds"
sudo pkill -f servodpirocon
sleep 1
sudo pkill -f servodmotorpitx
sleep 1
echo "Thank you"
sudo rm -rf $HDIR/scratchgpio

mkdir -p $HDIR/scratchgpio
chown -R $USERID:$GROUPID $HDIR/scratchgpio

cp scratchgpio_handler3.py $HDIR/scratchgpio
cp Adafruit_I2C.py $HDIR/scratchgpio
cp Adafruit_PWM_Servo_Driver.py $HDIR/scratchgpio

cp servodpirocon $HDIR/scratchgpio
chown -R $USERID:$GROUPID $HDIR/scratchgpio
chmod +x servodpirocon

cp servodmotorpitx $HDIR/scratchgpio
chown -R $USERID:$GROUPID $HDIR/scratchgpio
chmod +x servodmotorpitx

#Instead of copying the scratchgpio3.sh file, we will generate it
#Create a new file for scratchgpio3.sh
echo "#!/bin/bash" > $HDIR/scratchgpio/scratchgpio3.sh
echo "#Version 0.2 - add in & to allow simulatenous running of handler and Scratch" >> $HDIR/scratchgpio/scratchgpio3.sh
echo "#Version 0.3 - change sp launches rsc.sb from \"/home/pi/Documents/Scratch Projects\"" >> $HDIR/scratchgpio/scratchgpio3.sh
echo "#Version 0.4 - 20Mar13 meltwater - change to use provided name for home" >> $HDIR/scratchgpio/scratchgpio3.sh
echo "#Version 1.0 - 29Oct13 sw - change to cd into simplesi_scratch_handler to run servods OK" >> $HDIR/scratchgpio/scratchgpio3.sh
echo "sudo ps aux | grep 'python.*scratchgpio_handler3.py' | grep -v grep | awk '{print \$2}' | xargs sudo kill -9 " >> $HDIR/scratchgpio/scratchgpio3.sh
echo "cd $HDIR/scratchgpio" >> $HDIR/scratchgpio/scratchgpio3.sh
echo "sudo python scratchgpio_handler3.py &" >> $HDIR/scratchgpio/scratchgpio3.sh
echo "scratch --document \"$HDIR/Documents/Scratch Projects/rsc.sb\" &" >> $HDIR/scratchgpio/scratchgpio3.sh

chmod +x $HDIR/scratchgpio/scratchgpio3.sh
chown -R $USERID:$GROUPID $HDIR/scratchgpio/scratchgpio3.sh

cp blink11.py $HDIR

cp scratchgpio3.desktop $HDIR/Desktop


mkdir -p $HDIR/Documents
chown -R $USERID:$GROUPID $HDIR/Documents

mkdir -p $HDIR/Documents/Scratch\ Projects
chown -R $USERID:$GROUPID $HDIR/Documents/Scratch\ Projects

cp rsc.sb $HDIR/Documents/Scratch\ Projects
cp GPIOexample.sb $HDIR/Documents/Scratch\ Projects
cp blink11.sb $HDIR/Documents/Scratch\ Projects
chown -R $USERID:$GROUPID $HDIR/Documents/Scratch\ Projects
echo ""
echo "Finished."
