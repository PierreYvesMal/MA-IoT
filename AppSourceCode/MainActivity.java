// -*- mode: java -*-
package com.example.iot_hes.iotlab;

import android.Manifest;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.support.v4.app.ActivityCompat;
import android.support.v7.app.AppCompatActivity;
import android.os.Bundle;
import android.text.InputFilter;
import android.text.Spanned;
import android.util.Log;
import android.view.View;
import android.widget.Button;
import android.widget.EditText;
import android.widget.TextView;

// import java.io.Console;
import java.io.UnsupportedEncodingException;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import com.estimote.coresdk.common.config.EstimoteSDK;
import com.estimote.coresdk.common.config.Flags;
import com.estimote.coresdk.common.requirements.SystemRequirementsChecker;
import com.estimote.coresdk.observation.region.beacon.BeaconRegion;
import com.estimote.coresdk.recognition.packets.Beacon;
import com.estimote.coresdk.service.BeaconManager;
//MQTT
import com.blundell.iotcore.IotCoreCommunicator;
import java.util.concurrent.TimeUnit;
import android.util.Log;
import android.app.Activity;
import android.os.Bundle;
import android.os.Handler;
import android.os.HandlerThread;
public class MainActivity extends AppCompatActivity {

    //MQTT
    private IotCoreCommunicator communicator;
    private Handler handler;
    private static final String TAG = "IoTLab";
    private static final String VERSION = "0.1.9";
    private String msg ="";
    private boolean mustReturn = false;

    TextView PositionText;
    EditText Percentage;
    Button   IncrButton;
    Button   DecrButton;
    Button   LightButton;
    Button   StoreButton;
    Button   RadiatorButton;

    // In the "OnCreate" function below:
    // - TextView, EditText and Button elements are linked to their graphical parts (Done for you ;) )
    // - "OnClick" functions for Increment and Decrement Buttons are implemented (Done for you ;) )
    //
    // IoT Lab BeaconsApp minimal implementation:
    // - detect the closest Beacon and figure out the current Room
    //
    // TODO List for the whole project:
    // - Set the PositionText with the Room name
    // - Implement the "OnClick" functions for LightButton, StoreButton and RadiatorButton

    private BeaconManager beaconManager;
    private BeaconRegion region;

    // private static Map<Integer, String> rooms;
    static String currentRoom;

    @Override
    protected void onCreate(Bundle savedInstanceState) {

        //MQTT
        // Setup the communication with your Google IoT Core details
        communicator = new IotCoreCommunicator.Builder()
                .withContext(this)
                .withCloudRegion("us-central1") // ex: europe-west1
                .withProjectId("iotmalengre")   // ex: supercoolproject23236
                .withRegistryId("RaspiRegistry") // ex: my-devices
                .withDeviceId("AppDevice") // ex: my-test-raspberry-pi
                .withPrivateKeyRawFileId(R.raw.rsa_private)
                .build();



        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        Log.d(TAG, "Version: "+VERSION);

        if (ActivityCompat.checkSelfPermission(
                this,
                android.Manifest.permission.ACCESS_FINE_LOCATION
        ) != PackageManager.PERMISSION_GRANTED
        ) {
            ActivityCompat.requestPermissions(this,
                    new String[]{Manifest.permission.ACCESS_FINE_LOCATION},
                    2);
        }

        PositionText   =  findViewById(R.id.PositionText);
        Percentage     =  findViewById(R.id.Percentage);
        IncrButton     =  findViewById(R.id.IncrButton);
        DecrButton     =  findViewById(R.id.DecrButton);
        LightButton    =  findViewById(R.id.LightButton);
        StoreButton    =  findViewById(R.id.StoreButton);
        RadiatorButton =  findViewById(R.id.RadiatorButton);

        Flags.DISABLE_BATCH_SCANNING.set(true);
        Flags.DISABLE_HARDWARE_FILTERING.set(true);

        EstimoteSDK.initialize(getApplicationContext(), //"", ""
                               // These are not needed for beacon ranging
                                "smarthepia-8d8",                    // App ID
                                "771bf09918ceab03d88d4937bdede558"   // App Token
                               );
        EstimoteSDK.enableDebugLogging(true);

        // we want to find all of our beacons on range, so no major/minor is
        // specified. However the student's labo has assigned a given major
        region = new BeaconRegion(TAG, UUID.fromString("B9407F30-F5F8-466E-AFF9-25556B57FE6D"),
                30874,    // major -- for the students it should be the assigned one 17644
                                  null      // minor
                                  );
        beaconManager = new BeaconManager(this);
        // beaconManager = new BeaconManager(getApplicationContext());

        beaconManager.setRangingListener(new BeaconManager.BeaconRangingListener() {
                @Override
                public void onBeaconsDiscovered(BeaconRegion region, List<Beacon> list) {
                    Log.d(TAG, "Beacons: found " + String.format("%d", list.size()) + " beacons in region "
                          + region.getProximityUUID().toString());

                    if (!list.isEmpty()) {
                        Beacon nearestBeacon = list.get(0);
                        switch (nearestBeacon.getMinor())
                        {
                            case 10279: currentRoom = "1";
                                break;
                            case 43216: currentRoom = "10";
                                break;
                        }
                        //currentRoom = Integer.toString(nearestBeacon.getMinor());
                        String msg = "Room " +  currentRoom + "\n(major ID " +
                            Integer.toString(nearestBeacon.getMajor()) + ")";
                        Log.d(TAG, msg);
                        PositionText.setText(msg);
                    }
                }
            });

        beaconManager.setForegroundScanPeriod(2000, 1000);




        // Only accept input values between 0 and 100
        Percentage.setFilters(new InputFilter[]{new InputFilterMinMax("0", "100")});

        IncrButton.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) {
                int number = Integer.parseInt(Percentage.getText().toString());
                if (number<100) {
                    number++;
                    Log.d(TAG, "Inc: "+String.format("%d",number));
                    Percentage.setText(String.format("%d",number));
                }
            }
        });

        DecrButton.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) {
                int number = Integer.parseInt(Percentage.getText().toString());
                if (number>0) {
                    number--;
                    Log.d(TAG, "Dec: "+String.format("%d",number));
                    Percentage.setText(String.format("%d",number));
                }
            }
        });



        LightButton.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) {

                String node="2";

                //Should decide which lamp to light. This implies that the app should also be a subscriber. To implement.
                //Hardcoding it is no so terrible, could imagine that the user have to setup his network manually on the app...
                if(currentRoom=="1"){}
                else if(currentRoom == "10"){}

                doStuff("Light"+"."+node+"."+Percentage.getText().toString());
                // TODO Send HTTP Request to command light
                Log.d(TAG, Percentage.getText().toString());
            }
        });


        StoreButton.setOnClickListener(new View.OnClickListener() {
            //raw '3/4/1' 100 2 2  set valves/4/room1 percentage/2(size)/2(size)

            public void onClick(View v) {
                String val=String.valueOf(Integer.parseInt(Percentage.getText().toString())*255/100);

                String cmd="3/4/"+currentRoom+" "+val+" 2 2";
                String cmd2="3/4/"+String.valueOf(Integer.parseInt(currentRoom)+1)+" "+val+" 2 2";
                doStuff("Store"+"."+cmd+"."+cmd2);
                // TODO Send HTTP Request to command store
                Log.d(TAG, Percentage.getText().toString());
            }
        });


        RadiatorButton.setOnClickListener(new View.OnClickListener() {
            //raw '0/4/1' 100 2 2  set valves/4/room1 percentage/2(size)/2(size)
            public void onClick(View v) {
                String val=String.valueOf(Integer.parseInt(Percentage.getText().toString())*255/100);

                String cmd="0/4/"+currentRoom+" "+val+" 2 2";
                String cmd2="0/4/"+String.valueOf(Integer.parseInt(currentRoom)+1)+" "+val+" 2 2";
                doStuff("Rad"+"."+cmd+"."+cmd2);
                // TODO Send HTTP Request to command radiator
                Log.d(TAG, Percentage.getText().toString());
            }
        });


    }
    private void doStuff(String mess)
    {
        HandlerThread thread = new HandlerThread("MyBackgroundThread");
        thread.start();
        msg=mess;
        handler = new Handler(thread.getLooper());
        handler.post(connectOffTheMainThread); // Use whatever threading mechanism you want
        mustReturn=false;
    }

    // You will be using "OnResume" and "OnPause" functions to resume and pause Beacons ranging (scanning)
    // See estimote documentation:  https://developer.estimote.com/android/tutorial/part-3-ranging-beacons/
    @Override
    protected void onResume() {
        super.onResume();
        SystemRequirementsChecker.checkWithDefaultDialogs(this);

        beaconManager.connect(new BeaconManager.ServiceReadyCallback() {
            @Override
            public void onServiceReady() {
                String msg = "Beacons: start scanning...";
                PositionText.setText(msg);
                Log.d(TAG, msg);
                beaconManager.startRanging(region);
            }
        });
    }


    @Override
    protected void onPause() {
        beaconManager.stopRanging(region);

        super.onPause();

    }

    //MQTT
    private final Runnable connectOffTheMainThread = new Runnable() {
        @Override
        public void run() {
            communicator.connect();

            handler.post(sendMqttMessage);
        }
    };

    private final Runnable sendMqttMessage = new Runnable() {
        private int i=0;

        /**
         * We post 100 messages as an example, 1 a second
         */

        @Override
        public void run() {
            /*
            Log.w("run","Entering");
            if (i == 5) {
                return;
            }
            Log.w("run", String.valueOf(i));
            // events is the default topic for MQTT communication
            String subtopic = "events";
            // Your message you want to send


            String message = "Hello World " + i++;
            //String message = msg;
            communicator.publishMessage(subtopic, message);

            handler.postDelayed(this, TimeUnit.SECONDS.toMillis(1));
            */
            if(mustReturn)return;
            Log.i("sendMqttMessage", String.valueOf(i));
            Log.w("run","Running");
            // events is the default topic for MQTT communication
            String subtopic = "events";
            // Your message you want to send
            String message = msg;
            communicator.publishMessage(subtopic, message);

            handler.postDelayed(this, TimeUnit.SECONDS.toMillis(1));
            mustReturn=true;
            return;



        }
    };

    @Override
    protected void onDestroy() {
        Log.w("onDestroy","destroyed");
        communicator.disconnect();
        super.onDestroy();
    }
}


// This class is used to filter input, you won't be using it.

class InputFilterMinMax implements InputFilter {
    private int min, max;

    public InputFilterMinMax(int min, int max) {
        this.min = min;
        this.max = max;
    }

    public InputFilterMinMax(String min, String max) {
        this.min = Integer.parseInt(min);
        this.max = Integer.parseInt(max);
    }

    @Override
    public CharSequence filter(CharSequence source, int start, int end, Spanned dest, int dstart, int dend) {
        try {
            int input = Integer.parseInt(dest.toString() + source.toString());
            if (isInRange(min, max, input))
                return null;
        } catch (NumberFormatException nfe) { }
        return "";
    }

    private boolean isInRange(int a, int b, int c) {
        return b > a ? c >= a && c <= b : c >= b && c <= a;
    }
}


