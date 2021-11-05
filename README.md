# MA-IoT
Educational project for IoT at HES-SO mse

**********************
INSTALLATION
**********************
Clone the current repository (under ~/IoT/ if possible... Trying to update the code with relative path...)

//Android APP - End user software & Network layer  
Download app-release.apk on android device.

//KNX - Network layer  
Follow instructions from https://gitedu.hesge.ch/lsds/teaching/master/iot/knx  
But drop the --user from https://gitedu.hesge.ch/adrienma.lescourt/knxnet_iot/-/blob/master/README.md  
!!knx base folder has to be in the same folder as sub.py for the relative path to work (couldn't make it work with the ipv4 directly)  
Replace /knx/knx_client_script.py  

//ZWAVE - Network layer  
Follow instructions from https://gitedu.hesge.ch/lsds/teaching/master/iot/smart-building  
Replace backend.py  
note : raspberry is unusable (see ABOUT section) but only file to change on fresh install should be backend.py

//Sub - Support layer  
virtualenv env  
source env/bin/activate  
export GOOGLE_APPLICATION_CREDENTIALS=absolute_path_to/iotmalengre-153b229d624c.json  
pip3 install -r requirements.txt 

**********************
DEPLOY
**********************
!! Dimmers are hardcoded in app. This is to be changed. Couldn't test dynamically since raspberry is unusable. Room 1 will trigger node 2 and Romm 10 will trigger node 3
source env/bin/activate  

//KNX  
./knx/actuasim/actuasim.py &


//ZWAVE  
./flask-main.py -H [raspi ipv4]

//Sub  
export GOOGLE_APPLICATION_CREDENTIALS=absolute_path_to/iotmalengre-153b229d624c.json    
python3 sub.py iotmalengre my-subscription [ipv4]  

//App  
Launch app and witness changes in actuasim (only manual actions implemented)  


EXAMPLE TESTED ON FRESH UBUNTU INSTALL:  
cd~  
sudo apt-get install git  
git clone https://github.com/PierreYvesMal/MA-IoT  

cd MA-IoT  
git clone --recursive https://gitedu.hesge.ch/lsds/teaching/master/iot/knx.git  

//knxnet  
sudo apt-get update  
sudo apt-get install git python3-pip python-setuptools  
cd knx/knxnet  
pip3 install ./  
cd ..  
cp ~/MA-IoT/knx_client_script.py .  

//actuasim  
sudo apt-get update  
sudo apt-get install python3-pyqt5  
cd actuasim  
./actuasim.py &	//Leave this terminal open, start again in new one  


//sub  
cd \~/MA-IoT  
sudo apt-get install virtualenv  
virtualenv env  
source env/bin/activate  
export GOOGLE_APPLICATION_CREDENTIALS=\~/MA-IoT/iotmalengre-153b229d624c.json  
pip3 install -r requirements.txt  
python3 sub.py iotmalengre my-subscription 192.168.1.160:5000  

**********************
ABOUT
**********************

//Raspberry is unusable
While trying to implement the sub to raspberry, missing package led to broken package.

