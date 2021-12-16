// standard includes with descripitons
#include <chrono>    // hold sleep_for
#include <cstddef>   // byte functionality
#include <cstdio>    // standard input and output libarry
#include <cstring>   // provieds features to manipulate strings and arrays
#include <fstream>   // provieds in and output for files
#include <iomanip>   // to convert the bytes to hex
#include <iostream>  // standard input and output funcitons like cout
#include <queue>     // standard Queue include for first in first out queuing
#include <string>    // funcitons to manipulate c strings and arrays

using namespace std;

// serial communication libarry and data unpacking
#include <boost/asio.hpp>

// include ROS libs
#include "ros/ros.h"
#include "std_msgs/String.h"
#include <sensor_msgs/Range.h>

using namespace boost;

// class that holds function and variables for configuring MMwave sensor and is completed
class Configuration
{
public:
  string file_name;

  Configuration(string port, unsigned int baud_rate) : io(), serial(io, port) // defines the serial port and baudrate to be used
  {
    serial.set_option(asio::serial_port_base::baud_rate(baud_rate));
  }

  void sensorConfig()
  {
    ifstream config(file_name); // open the config file
    if (config.is_open());
    {
      string line;        
      string new_line = "\n";
      while (true)              // start loop that reads configs and writes them to the sensor.
      {
        getline(config, line);  // gets the first line
        string first_char = line.substr(0, 1);  // create a substring of the first character in the line
        if (first_char == "%")  // if the first character is % get next line
        {
          continue;
        }
        asio::write(serial, asio::buffer(line), asio::transfer_all());  // write the line to the sensor
        asio::write(serial, asio::buffer(new_line, new_line.size()));   // write a new line to the sensor
        string result;
        string end = "sensorStart";
        result = readConfigs();                                         // read the respons from the sensor
        cout << result << endl;
        if (result.find(end) != string::npos)                           // if the sensor respons with sensorStart break the loop as all configs has been sent 
        {
          break;
        }
      }
    }
  }
  string readConfigs()        // function reads the incomming responds from the configs setup.
  {
    char c;
    string result;
    string done = "Done";
    string CLI = "CLI";       

    for (;;)
    {
      asio::read(serial, asio::buffer(&c, 1));    //read characters from the senors
      switch (c)
      {
        case '\n':                                // wehn a new line is recived see if done is found if so return result 
          if (result.find(done) != string::npos)
          {
            return result;
          }
        default:
          result += c;                            // adds the character to the result variable. 
      }
    }
  }

private:
  asio::io_service io;
  asio::serial_port serial;
};

// class for reading the data sent by the MMwave sensor
class ReadProc
{
public:
  ReadProc(string port, unsigned int baud_rate)
    : io(), serial(io, port)  // set's up the port and baudrate that should be read by asio
  {
    serial.set_option(asio::serial_port_base::baud_rate(baud_rate));
  }

  struct __attribute__((packed)) Mmwave
  {
    //structure of the Header acording to the SDK
    uint32_t magic0;            // should be 84280068
    uint16_t Magic;             // should be 1800
    uint32_t version;           // is a static version number should be which is 50659332
    uint32_t total_packet_len;  // changing value based on the total packet length sent from the sensor 
    uint32_t platform;          // static platform number which should be is 682051 
    uint32_t frame_number;      // number of frames/ packages sent from the sensor starts at 1 and incremetns of 1 per packet sent. 
    uint32_t time_cpu_cycles;   // time information 
    uint32_t num_detected_obj;  // number of detected objects by the sensor includes 
    uint32_t num_TLVs;          // number of packages being sent as only point cloud informaiton is being send from the sensor this is a static 1  
    uint32_t sub_frame_number;  // shows which subframe was being used as not subrame are being used, but since no are sued it's in practise a static 0
    uint32_t tag;               // is the tag that identifies the type of informaiton being sent from the sensor 1 is = to point cloud information. 
    uint32_t length;            // length is actual length of the point cloud information that has been sent in the package should be either 64 or 48 less than total_packet_len 
  };

  struct __attribute__((packed)) Data_value
  {
    //uint32_t length;
    float coords[256];          // created a sturct that can hold up to 64 set's of coordinates should be fine for testing. 
  };

  float *readData(float y_coords[])
  {

    unsigned char buf_header[48]; // create a buffer with the size of the header structure. 

    asio::read(serial, asio::buffer(buf_header, 48)); // reads the incoming byte data into an buffer which size determins the amount of bytes that should be read
    size_t buf_header_length = sizeof(buf_header);
 
    const char * start = (const char *)memchr (buf_header, 50659332, buf_header_length); // looks in the buffer for where or if MMwave version is located and return a pointer to the first occurrence

    if(start != NULL)
    {
      const Mmwave * mmwave = reinterpret_cast<const Mmwave *>(start); //reinterprets and cast the read information into the Mmwave structure 


      // this is just to visualize the data that has been read should be delete once the script is fully working 
      cout << endl << "this is start: " << start << endl << endl;
      
      cout << "mmwave_magic0: " << mmwave->magic0 << endl;
      cout << "mmwave_Magic: " << mmwave->Magic << endl;
      cout << "mmwave_version: " << mmwave->version << endl;    
      cout << "mmwave_total_packet_len: " << mmwave->total_packet_len << endl;
      cout << "mmwave_platform: " << mmwave->platform << endl;
      cout << "mmwave_frame_number: " << mmwave->frame_number << endl;
      cout << "mmwave_time_cpu_cycles: " << mmwave->time_cpu_cycles << endl;
      cout << "mmwave_num_detected_obj: " << mmwave->num_detected_obj << endl;
      cout << "mmwave_num_TLVs: " << mmwave->num_TLVs << endl;
      cout << "mmwave_sub_frame_number: " << mmwave->sub_frame_number << endl;
      cout << "mmwave_tag: " << mmwave->tag << endl;
      cout << "mmwave_len: " << mmwave->length << endl << endl;

      if(mmwave->length >= 2000 || mmwave->sub_frame_number != 0 || mmwave->num_TLVs != 1)  // simple filter that sorts out the false readings 
      {
        cout << "return 0" << endl;
        return 0;
      }
      unsigned char buf_value[mmwave->length];                      // create a buffer with the length provided by the header 
      asio::read(serial, asio::buffer(buf_value, mmwave->length));  // read the value inforamtion into the the buffer

      const Data_value * data_value = reinterpret_cast<const Data_value *>(&buf_value);  // reinterpret cast the value data into the Data structure. 

      if(mmwave->num_detected_obj > 0)
      {                
        cout << "array struct: " << endl << endl;

        for(ptrdiff_t i = 0; i < mmwave->num_detected_obj*4; i += 4) // part of this for loop prints out the data value 
        // the other part gets the range information and saves it to be returned.
        {
          cout << i/4 << " array_x: " << data_value->coords[i] << " array_y: " << data_value->coords[i+1] << " array_z: " << 
          data_value->coords[i+2] << " array_velocity: " << data_value->coords[i+3] << endl;
          if(mmwave->num_detected_obj < 100)
          {
            y_coords[0] = mmwave->num_detected_obj;                 // appends the number of objects information to be used when publishing. 
          }
          // would add a filter here like in the pyhton script to sort out ground observerations and the likes. 
          y_coords[(i/4)+1] = data_value->coords[i+1];              // appends the y_coord to the variable to be returned. 

        }
        return y_coords;
      }
    }
    // else 
    // {
    //   cout << endl << "start is NULL " << endl << endl;
    // }
  }

private:
  boost::asio::io_service io;
  boost::asio::serial_port serial;
};

// main function starts the programe
int main(int argc, char **argv)
{
  // change these variables to fit with the configuation port of the MMwave sensor
  string config_port_address = "/dev/ttyUSB0";  // port address to the serial port for sensors config
  unsigned int config_port_baudrate = 115200;   // baudrate used on the config port of the sensor (default 115200)
  Configuration confport(config_port_address, config_port_baudrate); // create instance of configuration class 
  confport.file_name = "/home/pc/catkin_ws/src/beginner_tutorials/src/MMwave_Setup.cfg";  // file name of sensor config file
  confport.sensorConfig();

  cout << "end of config" << endl;

  // change these variables to fit with the data port of the MMwave sensor
  string port_address = "/dev/ttyUSB1";   // port addres to the serial port for sensors Data
  int port_baudrate = 921600;             // baudrate used on  the Data port of the sensor (default 921600)
  ReadProc dataport(port_address, port_baudrate); // create instance of the ReadProc class

  // ROS publishing setup
  ros::init(argc,argv, "mmwave_talker");
  ros::NodeHandle n;                      // create nodehanlder 
  ros::Publisher mmwave_pub = n.advertise<sensor_msgs::Range>("MMwave/range", 1000); // create the informaiton about the publishing 
  float y_coords[128];                    // creatte an array to hold the y_coordinats to be published 

  while(true)
  {
    sensor_msgs::Range r;                 // create an instance of the message type 
    float *recived_data = dataport.readData(y_coords);  // run the readData function to recive y_coords to be published
    if(recived_data != 0)
    {
      for(int i = 1; i< recived_data[0]+1; i++)
      { 
        r.header.stamp = ros::Time::now(); // gets the current ros time and appends it to the header stamp
        r.header.frame_id = "/MMwave_range";   
        r.radiation_type = 0;
        r.field_of_view = 1;
        r.min_range = 0.1;                  // minimum range accepted 0.1
        r.max_range = 4;                    // maximum range accepted 4
        r.range = recived_data[i];          // the actualy range value to be sent to the topic
        mmwave_pub.publish(r);              // publishes the range information to 
      }
    }
  }
}

// complie with this g++ mmwave_asio_test.cpp -o mmwave_asio_test -lfmt -std=c++17

