**********************
INSTALLATION
**********************
Clone the current repository (under ~/IoT/ if possible... Trying to update the code with relative path...)

//Android APP - End user software & Network layer
Download app-release.apk on android device.

//KNX - Network layer
Follow instructions from https://gitedu.hesge.ch/lsds/teaching/master/iot/knx
But drop the --user from https://gitedu.hesge.ch/adrienma.lescourt/knxnet_iot/-/blob/master/README.md
Replace /knx/knx_client_script.py

//ZWAVE - Network layer
Follow instructions from https://gitedu.hesge.ch/lsds/teaching/master/iot/smart-building
Replace backend.py

//Sub - Support layer


**********************
DEPLOY
**********************

//KNX
./knx/actuasim/actuasim.py &


//ZWAVE
./flask-main.py -H [raspi ipv4]

//Sub
virtualenv env
source env/bin/activate
export GOOGLE_APPLICATION_CREDENTIALS=absolute_path_to/iotmalengre-153b229d624c.json
pip install -r requirements.txt
python3 sub.py iotmalengre my-subscription [ipv4]

//App
Launch app and witness changes in actuasim (only manual actions implemented)


**********************
ABOUT
**********************
