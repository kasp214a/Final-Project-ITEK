#!/usr/bin/env python3

#FAQ
#what is TLV is an encoding method and stands for Tag, Length, Value 


#Sensor configuration uploader and data fetcher dependencies. 
import os
import sys                                  # allows access to the interpritor is used to exit python if something goes wrong 
import time                                 # used for sleep functions 
import struct                               # used to unpack the data sends from the sensor that is in a buffer 
import select 
import ctypes                               # provied C compatible data types 
import threading                            # allowes higher-level threading working well with multiprocessing 
import multiprocessing as mp                # let's python access more processors 
import serial                               # connects python to the serialports to read and write instructions to and from the MMwave sensor 
#from termcolor import cprint

#ROS dependencies 
import numpy as np                          # numpy libarry that has 
import rospy                                # imports ROS functionality to publish to topics 
from sensor_msgs.msg import Range           # imports the function that creates the Range message that's going to be sent  

#class that hold the functinos for reading and storing the data from the sensor
class ReadProc(mp.Process):

    def __init__(self, port, baud, stop_event, data_q): #defins the variables
        super(ReadProc, self).__init__(name='read')
        self.port = port                    #hold the infomation about the port that should be read
        self.baud = baud                    #hold the informaiton about the baudrate the port 
        self.data_q = data_q                #data_q variable to hold the read data 
        self._stop_event = stop_event       #when set will stop the thread
    
    def join(self, timeout=1):
        self._stop_event.set()
        return super(ReadProc,self).join(timeout)

    def open_dev(self):
        try:
            self.dev = serial.Serial(self.port, self.baud, timeout=0.01) # establishes connection to the data port with the given baud rate
            self.dev.flush()                # Clears the internal buffer of the Serial port.
            self.dev.flushInput()           # Clears input buffer of the Serial port. 

            return True
        except Exception as ex:             # if unable to connect to the Serial port retrun Execption. 
            print('failed to open data port')
            return False

    def run(self):
        print('reader pid: %d' %os.getpid())    # get's the current process id 
        self.open_dev()                         # open connection to the serial port

        while not self._stop_event.is_set():    # while stop_event is not called  

            try:                                # save the port settings to r 
                r,_,_ = select.select([self.dev], [], [], 0.1) 
            except:
                self._stop_event.set()
                break

            if not r:
                continue
            else:
                dev = r[0]                      # save the data port address to dev 
                data = dev.read(dev.in_waiting) # reads the data comming from the sensor and saves it to the data variable. 
                self.data_q.put(data)           # saves the data in the data_q 


        
        print('read proc end.')   

#class that parses the stored data from the sensor and launch the ross functions 
class ParseProc(mp.Process):                    #parser class for processing the raw data 

    MAGIC = b'\x02\x01\x04\x03\x06\x05\x08\x07' #magic number that is send at the begening of all packages from the sesnsor.  
    # deserialization infromation ofr the head pattern. 
    HEAD_PATTERN = 'I'*8
    # TAG_DICT is a sudo dictionary taht holds the deserialization for the diffrent types of messages sent by the sensor. 
    TAG_DICT = {1:('MSG_DETECTED_POINTS', 'f'*4), 2:('MSG_RANGE_PROF', 'H'), 3:('MSG_NIOSE_PROF', 'H'), 4:('MSG_AZIMUT_STATIC_HEAT_MAP', 'HH'),
    5:('MSG_RANGE_DOPPLER_HEAT_MAP', 'H'), 6:('MSG_STATS', 'I'*6), 7:('MSG_DETECTED_POINTS_SIDE_INFO', 'HH'), 8:('MSG_AZIMUT_ELEVATION_STATIC_HEAT_MAP', 'HH'), 9:('MSG_TEMP', 'II'+'H'*10)}

    def __init__(self, stop_event, data_q):     # initializing diffrent things like stop event 
        super(ParseProc, self).__init__(name='parse')

        self._stop_event = stop_event           #setup stop event
        self.data_q = data_q                    #setup the data_q

        self.raw_data = b''                     # tells that the following string is a byte string

        self.lock = threading.RLock()
    
    def join(self, timeout=1):                  # join  the parsing thread back to and close it.      
        self._stop_event.set()
        return super(ParseProc, self).join(timeout)

    def padding_thread(self): 
        while not self.padding_thread_stop_ev.is_set():
            try:
                data = self.data_q.get()        #gets the data put into the the data Queue from readproc. 
                with self.lock:                 #uses Multiprocessing Rlock to block other inputs unitl the next step is done.
                    self.raw_data += data
            except:
                break
        
        print('pading thread end.')
        return

    def run(self):
        print('parser pid: %d' %os.getpid())  #get's the current process id                                
        head_idx = -1
        next_head_idx = -1
        under_pack = False

        self.padding_thread_stop_ev = threading.Event()     #set padding event stop to be threading.Event
        padding_thread = threading.Thread(target=self.padding_thread) 
        padding_thread.start()                              #starts the Padding_thread

        while not self._stop_event.is_set():                # sort out the Magic Idetifier from the start of the package
            head_idx = self.raw_data.find(self.MAGIC)       #looks for the MAGIC identifyer in the raw data and returns it's possition.
            if head_idx == -1:                              #if MAGIC is not found continue until it is found
                
                continue

            next_head_idx = self.raw_data.find(self.MAGIC, head_idx+8)  #look to see if there's another MAGIC in the raw_data looking after the first one finished.
            if next_head_idx == -1:                                     #if not found sleep for 0.001 seconds and try again if unable too sleep break  
                
                try:
                    time.sleep(0.001)
                except:
                    break
                continue
            
            data = self.raw_data[head_idx+8: next_head_idx]             #set the variable data to start after Magic and end before the next Magic is found.
            with self.lock:                                             #uses Multiprocessing Rlock to block other inputs unitl the next step is done.
                self.raw_data = self.raw_data[next_head_idx:]           #reset raw_data to start from the next Magic number to get the data that follows
            self.parse_frame(data)                                      #start the parse_frame function with the data 

     
        print('parse proc end.')                                        #when stop_event is called start closing 
        self.padding_thread_stop_ev.set()
        padding_thread.join(1)
        time.sleep(1)
    
    def parse_frame(self, data): #function to parser and print the data sent by the sensor. 

        h_version, h_total_len, h_platform, h_frame_no, h_time_cpu_cycle, h_detect_obj_no, h_tlvs_no, h_sub_frame_no = struct.unpack('i'*8, data[:32]) #unpack the Header information 


        if len(data) != h_total_len-8:
            print( 'frame len error')
            return

        headerdata = '0x%x H_Ver, %d H_Length, 0x%x H_Platform, %d H_frame, %d H_Frame_no, %d Points_Observed, %d objects, %d H_sub_fram_no' %(h_version, h_total_len, h_platform, h_frame_no, h_time_cpu_cycle, h_detect_obj_no, h_tlvs_no, h_sub_frame_no)
        tlvs_tag_idx = 32 # where does the tag start  
        for i in range(h_tlvs_no):

            tlvs_tag, tlvs_len = struct.unpack('II', data[tlvs_tag_idx:tlvs_tag_idx+8]) # unpacks the TLVS_tag and Len 
            # assigned the vlaue part of TLV to be the between end of tag idx to end of tag idx plus the lentgh started by the TLV
            tlvs_val = data[tlvs_tag_idx+8 : tlvs_tag_idx+8+tlvs_len]          
            try:         
                tlvs_val = struct.unpack(self.TAG_DICT[tlvs_tag][1]*h_detect_obj_no, tlvs_val) # unpacks the data based on the tags, and some type of data not suite 
                Tlvs_value = str(tlvs_val)
                Convert_Coordinates(Tlvs_value)

            except Exception as ex:
                print('failed to unpack data: %s' %ex) #error for unsuported data from sensor or if an incomplete package length does not mach up with the expected 
                print(type(tlvs_val))  

            tlvs_tag_idx += (8+tlvs_len)

# class that start configuring the sensor and starts the read and parse proccess 
class Paser( object ):   

    CONF_PORT = '/dev/ttyUSB0' #same as the Application port used in the Demo Visualizer  
    CONF_BAUD = 115200 #Baud rate of the port standard 115200
    CONF_FILE = '/home/pc/catkin_ws/src/beginner_tutorials/scripts/MMwaveSetup.cfg' #path to configuation file to send to the snesor can be made using Demo Visualizer 
    DATA_PORT = '/dev/ttyUSB1' #same as the Data port used in the Demo visualizer
    DATA_BAUD = 921600 #Baud rate of the port standard 921600 


    def __init__(self):
        self.loop()


    def conf_dev(self): #if connection to device is there loads the CONF_FILE to the sensor  

        try: #try to establish connectino to conf port
            dev = serial.Serial(self.CONF_PORT, self.CONF_BAUD, timeout=0.015) 
        except Exception as ex:
            print(ex)
            return False
        
        try: #open CONF_FILE
            conf_lines = open(self.CONF_FILE).readlines()
        except Exception as ex:
            print(ex)
            return False
        
        for l in conf_lines:
            if l.startswith('%'): #if line estart with % go to next line 
                continue
            
            try: #wrtie the lines in the CONF_FILE and send the though Conf_Port and print it to terminal
                dev.write(l.encode('latin-1')) #encodes from standard UTF-8 into LATIN-1  
                print(dev.readlines())
            except Exception as ex:
                print(ex)
                return False
        dev.close() #close connection to conf port again 
        
        return True 

    def _launch_read_proc(self):

        if self.conf_dev():             #if Cong_file was sent without problem 
            print('dev conf done')
        else:                           #if the Cong_File failed to sent
            print('dev conf failed..')
            sys.exit(-1)                #exits script 

        self.read_proc = ReadProc(self.DATA_PORT, self.DATA_BAUD, self._stop_event, self.data_q) 
        self.read_proc.start()

    def _launch_parse_proc(self):
        self.parse_proc = ParseProc(self._stop_event, self.data_q)
        self.parse_proc.start()

    def loop(self):                         #starts a loop for python to run through to keep fetching data from the sensor when the loop is broken it will exit the program 
        print('main pid: %d' %os.getpid()) #get's the current process id 
        self.data_q = mp.Queue()
    
        self._stop_event = mp.Event()
        
        self._launch_read_proc()            #stats the mmwave reading thread / multi process
        self._launch_parse_proc()           #starts the mmwave parsing thread / multi process

        while 1:
            try:
                time.sleep(10)
            except:
                break
        
        self._stop_event.set()              #when the script is given a stop even / breaks out of the loop join and close the threads again.
        self.read_proc.join()
        self.parse_proc.join()
        

        print('bye')
        time.sleep(0.1)
        sys.exit()                          #close the script

# function that connects to a ROS topic and send the formated data
def talker(y_coord):
    
    rospy.init_node('MMwave_Sensor', anonymous=True) #setup the name of the node   
    range_Publish = rospy.Publisher('/platform/ultrasound/combined', Range, queue_size=10) #setup publisher to publish strings on MMwave topic 
    min_range = 0.1
    max_range = 4.0

    for i in y_coord:
        
        r = Range()
        r.header.stamp = rospy.Time.now() #stamp the header with the time 
        r.header.frame_id = '/base_link'
        r.radiation_type = 0
        r.field_of_view = 1
        r.min_range = min_range
        r.max_range = max_range
        r.range = i
        range_Publish.publish(r) #create the pointcloud with the header and the data 
        rospy.loginfo("observations sent successfully")

def check_coordinates(x_coord, y_coord, z_coord):
    pub_y = []
    empty_array = np.array([])
    for i in range(len(y_coord)):
        if -0.8 <= x_coord[i] <= 0.8:
            #object is detected between the range of -0.4 and 0.4 
            if 0 < z_coord[i] <=2:
                pub_y = np.append(pub_y, y_coord[i])
        if -2 <= x_coord[i] < -0.8 or 0.8 < x_coord[i] <= 2 and 1 < y_coord: 
            #if an object is beyond 0.4 and bellow 1 meters and is more than 1 meters away publish coord 
            if 0 < z_coord[i] <=2:
                pub_y = np.append(pub_y, y_coord[i])
    if not empty_array == 0:                
        talker(pub_y)

# funtion that converts the parsed data into the right format for sending via ROS
def Convert_Coordinates(Coordinates):
    Coordinates = Coordinates.replace('(',' ')  #changes "(" into a " "
    Coordinates = Coordinates.replace(')',' ')
    Coordinates = Coordinates.strip()           #remove excess " "
    Coordinates = Coordinates.split(',')        #split the at every , 
    FloatCoord = [float(i) for i in Coordinates]#change Coordiantes from str to float

    counter = 0 
    x_coord = []
    y_coord = []
    z_coord = []
    Velocity = []

    for i in range(len(FloatCoord)):            #loop through each item in the Floatcoord variable
        counter += 1                            #save each variable into it's own list
        if counter == 1:
            x_coord = np.append(x_coord, FloatCoord[i])
        if counter == 2:
            y_coord =  np.append(y_coord, FloatCoord[i])
        if counter == 3:                     
            z_coord = np.append(z_coord, FloatCoord[i])
        elif counter == 4:                      #the fourth item is the velocity of the object and isn't relavant for point cloud data 
            Velocity = np.append(Velocity,FloatCoord[i])
            counter = 0


    check_coordinates(x_coord, y_coord, z_coord)     #send the position coordianates to the talker funciton to be published on the desired topic

if __name__ == '__main__':
    p = Paser()
