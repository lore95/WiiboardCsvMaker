#include <Arduino.h>
#include "ADS131M04.h"
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>

ADS131M04 adc;
#define ADC_CLK_PIN 14
#define SCL_PIN 6
#define CS_PIN 3
#define MOSI_PIN 2
#define MISO_PIN 7
#define DRDY_PIN 4

#define TO_KG (77.0/1600000.0)
//Approximate conversion factor where 77KG averages to 1600000 in raw units
//This needs to be more accurately measured and likely should be configurable at runtime (and stored in flash)


BLEServer *pServer = NULL;
BLECharacteristic *pTxCharacteristic;
bool deviceConnected = false;
bool oldDeviceConnected = false;
uint8_t txValue = 0;

#define SERVICE_UUID           "6E400001-B5A3-F393-E0A9-E50E24DCCA9E" // UART service UUID
#define CHARACTERISTIC_UUID_RX "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"
#define CHARACTERISTIC_UUID_TX "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"
//Reusing the nordic BLE UART service, should probably reserve a unique UUID for easier filtering
//Should probably also structure the characteristics somewhat differently more suited for the application
//Maybe use writeable control-point (with op-codes similar to "Fitness machine service" from the ble standard) + datastream ch + read-only config ch


class WiiPlateServerCallbacks : public BLEServerCallbacks {
  void onConnect(BLEServer *pServer) {
    deviceConnected = true;
  };

  void onDisconnect(BLEServer *pServer) {
    deviceConnected = false;
  }
};

//Placeholder code for RX on BLE
class WiiPlateCallbacks: public BLECharacteristicCallbacks {

    void onWrite(BLECharacteristic *pCharacteristic) {
      String rxValue = pCharacteristic->getValue();

      if (rxValue.length() > 0) {
        Serial.println("*********");
        Serial.print("Received Value: ");
        for (int i = 0; i < rxValue.length(); i++)
          Serial.print(rxValue[i]);

        Serial.println();
        Serial.println("*********");
        uint32_t get_new_sample_time = rxValue.toInt();
      }
    }
};



void setup()
{
  Serial.begin(115200);

  //Init ADC
  ledcAttach(ADC_CLK_PIN, 4000000, 2);
  ledcWrite(ADC_CLK_PIN, 2);
  adc.begin(SCL_PIN, MISO_PIN, MOSI_PIN, CS_PIN, DRDY_PIN);

  delay(1000);
  Serial.println("");

  adc.setInputChannelSelection(0, INPUT_CHANNEL_MUX_AIN0P_AIN0N);
  adc.setInputChannelSelection(1, INPUT_CHANNEL_MUX_AIN0P_AIN0N);
  adc.setInputChannelSelection(2, INPUT_CHANNEL_MUX_AIN0P_AIN0N);
  adc.setInputChannelSelection(3, INPUT_CHANNEL_MUX_AIN0P_AIN0N);
  adc.setChannelPGA(0, CHANNEL_PGA_128);
  adc.setChannelPGA(1, CHANNEL_PGA_128);
  adc.setChannelPGA(2, CHANNEL_PGA_128);
  adc.setChannelPGA(3, CHANNEL_PGA_128);
  adc.setOsr(OSR_4096);



  //Init BLE service (boilerplate for Nordic UART service)
  BLEDevice::init("WiiPlate");
  pServer = BLEDevice::createServer();
  pServer->setCallbacks(new WiiPlateServerCallbacks());

  // Create the BLE Service
  BLEService *pService = pServer->createService(SERVICE_UUID);

  // Create a BLE Characteristic
  pTxCharacteristic = pService->createCharacteristic(CHARACTERISTIC_UUID_TX, BLECharacteristic::PROPERTY_NOTIFY);

  pTxCharacteristic->addDescriptor(new BLE2902());

  BLECharacteristic *pRxCharacteristic = pService->createCharacteristic(CHARACTERISTIC_UUID_RX, BLECharacteristic::PROPERTY_WRITE);

  pRxCharacteristic->setCallbacks(new WiiPlateCallbacks());

  pService->start();

  // Start advertising
  pServer->getAdvertising()->addServiceUUID(pService->getUUID());
  pServer->getAdvertising()->start();
  Serial.println("Waiting a client connection to notify...");
}
#define TARE_SAMPLES 500
void loop()
{
  adcOutput res;
  int32_t tare[4] = {0, 0, 0, 0};
  int32_t accumulate_average_samples = 50;
  double accumulated_value[4] = {0,0,0,0};
  uint32_t average_count = 0;
  float send_value[4];
  
  delay(100);

  for(int i = 0; i < TARE_SAMPLES; i++){
    while(!adc.isDataReady());
    res = adc.readADC();
    tare[0] += res.ch0;
    tare[1] += res.ch1;
    tare[2] += res.ch2;
    tare[3] += res.ch3;
  }

  for(int i = 0; i < 4; i++) tare[i] /= 500;
  esp_ble_tx_power_set(ESP_BLE_PWR_TYPE_DEFAULT, ESP_PWR_LVL_N15);
  while (1)
  {
    //Waiting for new sample
    if (adc.isDataReady())
    {  
      //When sample is ready, read and then send
      res = adc.readADC();
      accumulated_value[0] += (float)(res.ch0 - tare[0]);//*TO_KG;
      accumulated_value[1] += (float)(res.ch1 - tare[1]);//*TO_KG;
      accumulated_value[2] += (float)(res.ch2 - tare[2]);//*TO_KG;
      accumulated_value[3] += (float)(res.ch3 - tare[3]);//*TO_KG;
      average_count++;
      if(average_count >= accumulate_average_samples){
        
        uint32_t time = micros();
        char str[1024];
        sprintf(str, "Time:%d,V1:%.3f,V2:%.3f,V3:%.3f,V4:%.3f\n", time, accumulated_value[0]/(float)accumulate_average_samples, accumulated_value[1]/(float)accumulate_average_samples, accumulated_value[2]/(float)accumulate_average_samples, accumulated_value[3]/(float)accumulate_average_samples);
        Serial.print(str);
        if(deviceConnected){
          pTxCharacteristic->setValue((uint8_t*)str, strlen(str));
          pTxCharacteristic->notify();
        }
        average_count = 0;
        for(int i = 0; i < 4; i++) {accumulated_value[i] = 0.0;}
      } 
      
    }

    //BLE connection management (branch is not normally taken except during disconnection events)
    if (!deviceConnected && oldDeviceConnected) {
        delay(500); // give the bluetooth stack the chance to get things ready
        pServer->startAdvertising(); // restart advertising
        Serial.println("start advertising");
        oldDeviceConnected = deviceConnected;
    }
    // connecting
    if (deviceConnected && !oldDeviceConnected) {
        oldDeviceConnected = deviceConnected;
    }
  }
}