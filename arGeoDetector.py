#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""
Created on Wed Mar 20 19:43:40 2019

@author: Richard Ferguson K3FRG
         k3frg@arrl.net
"""

import os
from pathlib import Path
import signal
import sys
import math
import re
import time
import datetime
import threading
from threading import Thread
#import io
import logging
import logging.handlers
import serial
import xml.etree.ElementTree

from enum import Enum

from optparse import OptionParser
from configparser import ConfigParser

try:
    from appdirs import AppDirs
except ImportError:
    class AppDirs:
        def __init__(self, appname, appauthor):
            self.user_config_dir = os.path.join(
                os.path.expanduser("~"),
                ".config",
                appname
            )

VERSION = "0.3.3"

STATE_ABBREVIATIONS = dict(zip(
    "Alabama Alaska Arizona Arkansas California Colorado Connecticut Delaware Florida Georgia Hawaii Idaho Illinois Indiana Iowa Kansas Kentucky Louisiana Maine Maryland Massachusetts Michigan Minnesota Mississippi Missouri Montana Nebraska Nevada NewHampshire NewJersey NewMexico NewYork NorthCarolina NorthDakota Ohio Oklahoma Oregon Pennsylvania RhodeIsland SouthCarolina SouthDakota Tennessee Texas Utah Vermont Virginia Washington WestVirginia Wisconsin Wyoming".split(),
    "AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY".split()))



class geoMsg(Enum):
    GRID  = 1
    CNTY  = 2
    STAT  = 3
    TIME  = 4
    GPS   = 5
    NOTIF = 6
    POPUP = 7
    REPLAY= 8
    GPS_STATUS = 9

class geoBoundary():
    def __init__(self, name, abbr, state_abbr=""):
        self.name = name
        self.abbr = abbr
        self.state_abbr = state_abbr
        self.coords = []
        
    def addCoord(self, xy):
        # xy is a (x,y) tuple
        self.coords.append(xy)
    
    def wrapCoord(self):
        self.coords.append(self.coords[0])
    
    def coords2mxb(self, c1,c2):
        # solve for line equation
        (c1x,c1y) = c1
        (c2x,c2y) = c2
    
        m = (c2y-c1y) / (c2x-c1x)
        b = c1y - m*c1x
        #print "m>%f b>%f" % (m, b)
        return (m,b)
      
    def contains(self, xy):
        (x,y) = xy

        test_cnt = 0
        coord_cnt = 0

        for i in range(len(self.coords)-1):
            # Test against sequential coordinates
            (cx1,cy1) = self.coords[i]
            (cx2,cy2) = self.coords[i+1]
            # the NMEA X coordinate must fall between the two test coords
            if x == cx1:
                if cy1 < y:
                    test_cnt -= 1
                else:
                    test_cnt += 1
                coord_cnt +=1
            
            elif x == cx2:
                if cy2 < y:
                    test_cnt -= 1
                else:
                    test_cnt += 1
                coord_cnt +=1
                
            elif x >= cx1 and x <= cx2 or x >= cx2 and x <= cx1:
                # Solve for line equation y=mx+b
                (m,b) = self.coords2mxb(self.coords[i],self.coords[i+1])
                # Calculate Y coordinate from equation
                ycalc = m*x+b
                
                # Compare calculated Y vs NMEA Y
                if ycalc < y:
                    test_cnt -= 1
                else:
                    test_cnt += 1
                    
                # Record how many coordinate pairs satisfy the test
                coord_cnt += 1
                
   #     print("%s: %d %d" % (self.abbr, test_cnt, coord_cnt))        
        if not ((coord_cnt - abs(test_cnt)) % 4 == 0):       
            #print("TRUE> %s: %d %d" % (self.abbr, test_cnt, coord_cnt))        
            return True
        else:
            return False
    
class arGeoDetector(Thread):
    def __init__(self, serial, cb, log=0, nmea=0, mode=0):
        Thread.__init__(self)
        
        self.boundaries = []
        self.mode = 0 # 0 = gui, 1 = cli
        self.verbose = False
        
        self.log_main = log
        self.log_nmea = nmea
        
        self.last_grid = ""
        self.last_qth = ""
        self.last_datetime = datetime.datetime.now(datetime.timezone.utc)
         
        self.gps_lock = False
        self.gps_datetime = datetime.datetime.now(datetime.timezone.utc)

        self.bnd_warn = 0
        
        self.state = 0
        self.in_state = -1
        self._do_exit = 0
        self.lock = threading.Lock()

        self.com = serial
        self.msgCB = cb
        
    def loadBoundaries(self, filename):
        self.boundaries = []
        path = Path(filename)
        files = sorted(path.glob("*.kml")) if path.is_dir() else [path]
        for boundary_file in files:
            self._loadBoundaryFile(boundary_file)
        if not files:
            self.msgCB((geoMsg.STAT, "No KML files found in [%s]" % filename))
        self.log("Known Counties: %d" % len(self.boundaries))

    def _loadBoundaryFile(self, filename):
        state_abbr = next((abbr for state, abbr in STATE_ABBREVIATIONS.items()
                           if Path(filename).stem.startswith("Overlay" + state)), "")
        
        # Load Kml file into string so I can remove the 
        # xmlns="http://earth.google.com/kml/2.1" string
        # from the <kml> tag.  I don't know why but this 
        # breaks the subsequent element tree?????
        
        xmlstr = ""
        try:
            kmlin = open(filename)
            for line in kmlin.readlines():
                xmlstr += line.replace(" xmlns=\"http://earth.google.com/kml/2.1\"","")
        except:
            self.msgCB((geoMsg.STAT, "Error reading boundary file [%s]!" % filename))
            #print ("Error reading boundary file [%s]!" % filename)
            #quit(1)
            return
        
        e = xml.etree.ElementTree.fromstring(xmlstr)
        #e = xml.etree.ElementTree.parse(filename).getroot()

        for xplacemark in e[0].iter('Placemark'):
            for xname in xplacemark.iter('name'):
                # extract name info
                # Form: 'Fauquier=FAU 1'
                # only process '1' entries
                m = re.search('(\\w+)=(\\w+) 1', xname.text)
                if (m): # If match succeeds
                    name = m.group(1)
                    abbr = m.group(2)
                    self.log ("Loading %s(%s)" % (abbr, name))
                    # Create new boundary object
                    boundary_state = "DC" if state_abbr == "MD" and abbr == "DC" else state_abbr
                    bnd = geoBoundary(name, abbr, boundary_state)
                    
                    # Add coordinates to boundary object
                    # Form: '-75.87614423,37.55153989'
                    for xcoords in xplacemark.iter('coordinates'):
                        lines = xcoords.text.strip().split('\n')
                        for line in lines:
                            sline = line.strip() # remove whitespace
                            xy = sline.split(',')
                            #print ("X> %s, Y> %s" % (xy[0], xy[1]))
                            # Add coordinate to object
                            bnd.addCoord((float(xy[0]), float(xy[1])))
                            
                        # Wrap coordinate list by copying entry 0 to the end
                        bnd.wrapCoord()
                    
                    self.boundaries.append(bnd)
        self.log("Boundary file loaded")
    
#    def enableLog(self, filename):
#        try:
#            self.log_nmea = open("%s.nmea" % filename, "w")
#        except:
#            print ("Error:  can not open nmea log file [%s.nmea]" % filename)
#            quit(1)
#        
#        try:
#            self.log_caic = open("%s.log" % filename, "w")
#        except:
#            print ("Error:  can not open caic log file [%s.log]" % filename)
#            quit(1)
#                
#    def closeLog(self):
#        self.log_nmea.close()
#        self.log_caic.close()
    
    def log(self, logstr, status=1):
        if self.log_main:
            self.log_main.info(logstr)
        
        if status:
            self.msgCB((geoMsg.STAT,logstr))

    def logNMEA(self, logstr):
        if self.log_nmea:
            self.log_nmea.info(logstr)
           
    def wdTick(self):
        self.wd = datetime.datetime.now()
        
    def wdCheck(self, timeout=15):
        if datetime.datetime.now() - self.wd > datetime.timedelta(minutes=timeout):
            #self._do_exit = 1
            return 1
        return 0
            
#    def clirun(self):    

    def openPort(self):
        #print ("open port")
        with self.lock:
            if not self.com.is_open:
                self.state = 1
         
    def closePort(self):
        #print ("close port")
        with self.lock:
            self.state = 0
        
        while not self.in_state == 0:
            time.sleep(0.1)
            
        with self.lock:
            if self.com.is_open:
                self.com.close()
    
    def stop(self):
        self._do_exit = 1
        
    def run(self):
        ## Serial Thread
        
        ## States
        ## 0 = Wait for port information
        ## 1 = Open port
        ## 2 = Wait for serial data
        ## 3 = Wait for Time/Date sync
        ## 4 = Process serial data
        
        self.wdTick()
        uniErrLimit = 3
        #self.state = 0
        while not self._do_exit:
            # State 0
            if self.state == 0:
                self.wdTick()
                self.in_state = 0
                uniErrLimit = 3 # reset unicode error limit
                self.log("Idle")
                # auto exit if in cli mode
                if self.mode == 1:
                    self._do_exit = 1
                while self.state == 0 and not self._do_exit:
                    time.sleep(1)
                
            # State 1
            if self.state == 1:
                self.in_state = 1
                self.log("Opening serial port [%s @ %s]" % (self.com.port, self.com.baudrate))
                fails_to_go = 5
                while self.state == 1 and not self._do_exit:
                    try:
                        self.com.open()
                        with self.lock:
                            self.state = 2
                        self.wdTick()
                    except serial.serialutil.SerialException as e:
                        self.log("Error opening serial port [%s]" % self.com.port)
                        if self.wdCheck(1):
                            with self.lock:
                                self.state = 0
                        fails_to_go -= 1
                        if not fails_to_go:
                            self.state = 0
                        time.sleep(2)
            
            # State 2
            if self.state == 2:
                self.in_state = 2
                self.log("Waiting for initial GPS data")
                while self.state == 2 and not self._do_exit:
                    if self.com.in_waiting > 0:
                        with self.lock:
                            self.state = 3
                        self.wdTick()
                    elif self.wdCheck(5):
                        self.log("Timeout waiting for initial GPS data, closing port")
                        with self.lock:
                            self.com.close()
                            self.state = 0
                    else:
                        time.sleep(1)
                
            # State 3
            if self.state == 3:
                self.in_state = 3
                self.log("Waiting for GPS Date/Time sync")
                while self.state == 3 and not self._do_exit:
                    try:
                        with self.lock:
                            buf = self.com.readline().decode().rstrip()
                        if buf:
                            self.logNMEA(buf)
                    
                            # process GPRMC lines for date/time        
                            m = re.search('^\\$GPRMC', buf)
                            if (m):
                                try:
                                    self.updateNmeaRmcDateTime(buf)
                                except ValueError:
                                    continue
                                with self.lock:
                                    self.log("Date/Time synced!")
                                    self.state = 4
                                self.wdTick()
                                
                    except UnicodeDecodeError:
                        uniErrLimit -= 1
                        self.log("com data error! check baud rate")
                        self.msgCB((geoMsg.GRID,"-"))
                        self.msgCB((geoMsg.CNTY,("-","-")))
                        if uniErrLimit <= 0:
                            with self.lock:
                                self.com.close()
                                self.state = 0
                    except serial.serialutil.SerialException as e:
                        self.log("com error [%s]" % (str(e)))
                        self.msgCB((geoMsg.GRID,"-"))
                        self.msgCB((geoMsg.CNTY,("-","-")))
                        with self.lock:
                            self.com.close()
                            self.state = 1
                    except:
                        # likely empty string so decode fails
                        pass
            
                    if self.wdCheck(5):
                        self.log("Timeout waiting for GPS Date/Time sync, closing port")
                        with self.lock:
                            self.com.close()
                            self.state = 0

            # State 4
            if self.state == 4:
                self.in_state = 4
                self.log("Processing GPS data")
                while self.state == 4 and not self._do_exit:
                    try:
                        with self.lock:
                            buf = self.com.readline().decode().rstrip()
                        if buf:
                            self.logNMEA(buf)
                   
                            # process GPRMC lines for date/time        
                            m = re.search('^\\$GPRMC', buf)
                            if (m):
                                try:
                                    self.updateNmeaRmcDateTime(buf)
                                except ValueError:
                                    pass
        
                            # process GPGGA lines for location
                            m = re.search('^\\$GPGGA', buf)
                            if (m):
                                changed = 0
                                # Update time
                                self.updateNmeaGgaTime(buf)
                                
                                # Extract decimal and find county/city
                                try:
                                    xy = self.getNmeaGgaCoords(buf)
                                except ValueError:
                                    continue
                                
                                grid = self.calcGridSquare(xy)
                                self.msgCB((geoMsg.GRID,grid))
                                if self.last_grid != grid:
                                    # new grid detected
                                    self.last_grid = grid
                                    changed += 1
                                
                                qth = self.findCAIC(xy)
                                self.msgCB((geoMsg.CNTY,(qth.name, qth.abbr, qth.state_abbr)))
                                if self.last_qth != (qth.state_abbr, qth.abbr, qth.name):
                                    # New county/city detected
                                    self.last_qth = (qth.state_abbr, qth.abbr, qth.name)
                                    changed += 2
                                
                                if changed: # or (self.gps_datetime - self.last_datetime) >= datetime.timedelta(seconds=30):
                                    self.msgCB((geoMsg.NOTIF, changed))
                                    self.last_datetime = self.gps_datetime
                                    self.log("%s %s(%s)" % (grid, qth.name, qth.abbr))

                                self.wdTick()
                    except UnicodeDecodeError:
                        uniErrLimit -= 1
                        self.log("com data error! check baud rate")
                        self.msgCB((geoMsg.GRID,"-"))
                        self.msgCB((geoMsg.CNTY,("-","-")))
                        if uniErrLimit <= 0:
                            with self.lock:
                                self.com.close()
                                self.state = 0
                    except serial.serialutil.SerialException as e:
                        self.log("com error [%s]" % (str(e)))
                        self.msgCB((geoMsg.GRID,"-"))
                        self.msgCB((geoMsg.CNTY,("-","-")))
                        with self.lock:
                            self.com.close()
                            self.state = 1
                    except:
                        print("empty string?", file=sys.stderr)
                        # likely empty string so decode fails
                        pass
            
                    if self.wdCheck(2):
                        self.log("Timeout waiting for GPS location data, restarting lock sequence")
                        with self.lock:
                            self.state = 2
        
        # Clean up com if still open        
        if self.com.is_open:
            self.com.close()
            
    def replayFile(self, filename, speed = 0):
        self.log("Replaying {} NMEA GPS file".format(filename))
        with open(filename) as fp:
            for buf in fp:
                #print(buf)
                time.sleep(speed)
                # process GPRMC lines for date/time        
                m = re.search('^\\$GPRMC', buf)
                if (m):
                    try:
                        self.updateNmeaRmcDateTime(buf)
                    except ValueError:
                        pass
                # process GPGGA lines
                m = re.search('^\\$GPGGA', buf)
                if (m):
                    try:
                        xy = self.getNmeaGgaCoords(buf)
                    except ValueError:
                        continue
                    grid = self.calcGridSquare(xy)
                    qth = self.findCAIC(xy)
                    self.msgCB((geoMsg.GRID,grid))
                    self.msgCB((geoMsg.CNTY,(qth.name, qth.abbr, qth.state_abbr)))
                    self.log("%s %s(%s)" % (grid, qth.name, qth.abbr))
        self.log("Replay complete")
        self.msgCB((geoMsg.REPLAY,0))
            
    # Sync datetime on RMC strings
    def updateNmeaRmcDateTime(self, nmea_str):
        #$GPRMC,154007.00,A,3835.17128,N,07745.57692,W,0.070,,220319,,,A*67
        nmea_fields = nmea_str.split(',')
        if not nmea_fields[1][:2]:
            raise ValueError("RMC record does not contain valid date and time")
        h = int(nmea_fields[1][:2])
        m = int(nmea_fields[1][2:4])
        s = int(nmea_fields[1][4:6])
        D = int(nmea_fields[9][:2])
        M = int(nmea_fields[9][2:4])
        Y = 2000 + int(nmea_fields[9][4:6])
        self.gps_datetime = datetime.datetime(Y,M,D,h,m,s,tzinfo=datetime.timezone.utc)
        self.gps_lock = True
        self.msgCB((geoMsg.TIME, self.gps_datetime.strftime("%Y/%m/%d %H:%M:%S %Z")))
        
    # Sync location on GGA strings
    def updateNmeaGgaTime(self, nmea_str):
        # Form: $GPGGA,002852.00,3835.14680,N,07745.58318,W,1,03,5.60,127.9,M,-34.5,M,,*61
        nmea_fields = nmea_str.split(',')
        if not nmea_fields[1][:2]:
            raise ValueError("GGA record does not contain valid time")
        h = int(nmea_fields[1][:2])
        m = int(nmea_fields[1][2:4])
        s = int(nmea_fields[1][4:6])
        self.gps_datetime.replace(hour=h, minute=m, second=s)
        self.msgCB((geoMsg.TIME, self.gps_datetime.strftime("%Y/%m/%d %H:%M:%S %Z")))
    
    def getNmeaGgaCoords(self, nmea_str):
        # Form: $GPGGA,002852.00,3835.14680,N,07745.58318,W,1,03,5.60,127.9,M,-34.5,M,,*61
        nmea_fields = nmea_str.split(',')
        fix = int(nmea_fields[6] or 0)
        satellites = int(nmea_fields[7] or 0)
        self.msgCB((geoMsg.GPS_STATUS, (fix, satellites)))
        if fix == 0:
            raise ValueError("GGA record has no GPS fix")
        if not nmea_fields[2]:
            raise ValueError("GGA record does not contain valid coordinates")
             #           return (0,0)
        
        nmea_y = nmea_fields[2]
        nmea_yd = nmea_fields[3]
        nmea_x = nmea_fields[4]
        nmea_xd = nmea_fields[5]
        
        y = float(nmea_y[0:2]) + (float(nmea_y[2:])/60.0)
        if nmea_yd == 'S':
            y = 0 - y
        
        x = float(nmea_x[0:3]) + (float(nmea_x[3:])/60.0)
        if nmea_xd == 'W':
            x = 0 - x
        
        self.msgCB((geoMsg.GPS, "%s%s  %s%s" % (nmea_y,nmea_yd,nmea_x,nmea_xd)))
#        print ("NMEA(LON:%f,LAT:%f) " % (x, y), end='')
        return (x,y)
    
    def findCAIC(self, xy):
        (nx,ny) = xy
        
        # return if bogus data
        if nx == 0 and ny == 0:
            return
        
        qth_list = []
        for bnd in self.boundaries:
            if bnd.contains(xy):
                qth_list.append(bnd)
        
        # If more than one boundaries match, solve for correct boundary
        # 1) city and county, find city in county
        # 2) county/county overlap, just pick one
        qth = False
        if len(qth_list) == 1:
            qth = qth_list[0]
        elif len(qth_list) > 1:
            for i in range(0,len(qth_list)):
                for j in range(0, len(qth_list)):
                    if i != j:
                        #print ("%s vs %s" % (qth_list[i].abbr, qth_list[j].abbr))
                        c = qth_list[j].coords[0]
                        if not qth_list[i].contains(c):
                            qth = qth_list[i]
        else:
            if self.bnd_warn == 0:
                print("Warning: coordinate did not match boundary file", file=sys.stderr)
                self.bnd_warn = 1
            return  geoBoundary("Unknown", "UNK")

        if not qth:
            qth = qth_list[0]
            
        self.bnd_warn = 0
        return qth
            
        #print ("QTH> %s" % (qth.abbr))

    def calcGridSquare(self, xy):
        (nx, ny) = xy
        
        # move origin to bottom left of the world 
        nx += 180
        ny += 90
        
        # field is 20x10 degree rect
        xf = math.floor(nx / 20)
        yf = math.floor(ny / 10)
        
        # convert to ascii capitals A-R
        xfc = str(chr(65 + xf))
        yfc = str(chr(65 + yf))
        
        # square is 2x1 degree rect
        xs = math.floor((nx-(xf*20)) / 2)
        ys = math.floor((ny-(yf*10)) / 1)
        
        # convert to ascii numbers 0-9
        xsc = str(xs)
        ysc = str(ys)

        # subsquare is (2/24)x(1/24) degree rect
        xss = math.floor((nx-(xf*20)-(xs*2)) / (2/24))
        yss = math.floor((ny-(yf*10)-(ys*1)) / (1/24))

        # convert to ascii capitals A-R
        xssc = str(chr(97 + xss))
        yssc = str(chr(97 + yss))

        return ("%s%s%s%s%s%s" % (xfc, yfc, xsc, ysc,xssc,yssc))

class geoBase():
    def __init__(self, opts, geoCB):
        self.mode = 0 # 0 = serial, 1 = replay
        
        # Setup Directories
        # Check for pyinstaller runtime
        if getattr(sys, 'frozen', False):
            self.appPath = sys._MEIPASS
        else:
            self.appPath = os.path.dirname(os.path.abspath(__file__))

        # Get standard directory for local files
        self.appDirs = AppDirs("arGeoDetector", "K3FRG")
        try:
            os.makedirs(self.appDirs.user_config_dir, exist_ok=True)
        except:
            print("Error: Unable to create local log directory! [%s]" % self.appDirs.user_config_dir, file=sys.stderr)
            exit(1)

        # Init filenames
        self.settingsFile = os.path.join(self.appDirs.user_config_dir, "config.ini")
        self.logFile = os.path.join(self.appDirs.user_config_dir,"log.txt")
        self.nmeaFile = os.path.join(self.appDirs.user_config_dir,"nmea.txt")
        
        # Open logs
        self.initLogs()
        
        # Load settings
        self.config = ConfigParser()
        self.initSettings()
        self.readSettings()
        # process command line options if present
        self.cliSettings(opts)
       
        # Init serial object
        # Typical GPS baudrate is 4800, override later if needed
        self.serial = serial.Serial(baudrate=4800, timeout=1)
                
        # Create geoDetector object
        self.geoDet = arGeoDetector(self.serial, geoCB, self.logMain, self.logNMEA)

    def initLogs(self):
        # Main log
        try:
            formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
            handler = logging.handlers.RotatingFileHandler(self.logFile,maxBytes=1024*1024, backupCount=5)
            handler.setFormatter(formatter)

            consoleHandler = logging.StreamHandler(sys.stderr)
            consoleHandler.setFormatter(formatter)

            self.logMain = logging.getLogger("main")
            self.logMain.setLevel(logging.INFO)
            self.logMain.addHandler(handler)
            self.logMain.addHandler(consoleHandler)
        except:
            print("Error: Unable to initialize log file! [%s]" % self.logFile, file=sys.stderr)
            exit(1)

        # NMEA log
        try:
            formatter = logging.Formatter('%(message)s')
            handler = logging.FileHandler(self.nmeaFile)
            handler.setFormatter(formatter)
        
            self.logNMEA = logging.getLogger("nmea")
            self.logNMEA.setLevel(logging.INFO)
            self.logNMEA.addHandler(handler)
        except:
            print("Error: Unable to initialize NMEA log file! [%s]" % self.nmeaFile, file=sys.stderr)
            exit(1)

    def initSettings(self):
        # Create sections
        sects = ["GUI", "BOUNDARY", "SERIAL", "ALERTS"]
        for sect in sects:
            if not self.config.has_section(sect):
                self.config.add_section(sect)
        self.config.set('BOUNDARY', 'file', os.path.join(self.appPath, 'boundaries'))
        
    def readSettings(self):
        self.config.read(self.settingsFile)

    def writeSettings(self):
        os.makedirs(self.appDirs.user_config_dir, exist_ok=True)
        with open(self.settingsFile, 'w') as configfile:
            self.config.write(configfile)
            
    def cliSettings(self, opts):
        # save opts if needed later
        self.opts = opts
        
        if opts.port:
            self.config.set('SERIAL','port', opts.port)
        
        if opts.rate:
            self.config.set('SERIAL','rate', "%d" % opts.rate)
        
        if opts.bndfile:
            if not os.path.isfile(opts.bndfile) and not os.path.isdir(opts.bndfile):
                print("Error: geographic boundary file not found [%s]\n" % opts.bndfile, file=sys.stderr)
                exit(1)
            else:
                self.config.set('BOUNDARY','file', opts.bndfile)
        
        if opts.nmeaFile:
            if not os.path.isfile(opts.nmeaFile):
                print("Error: NMEA data file not found [%s]\n" % opts.nmeaFile, file=sys.stderr)
                exit(1)
            else:
                self.mode = 1
                self.replayFile = opts.nmeaFile

class geoCLI(geoBase):
    def __init__(self, opts):
        print("arGeoDetector %s by K3FRG" % VERSION, file=sys.stderr)
        
        super().__init__(opts, self.geoCB)
        
        bnd = self.config.get('BOUNDARY','file', fallback=None)
        if bnd:
            self.geoDet.loadBoundaries(bnd)
        

    def sigint(self, sig, frame):
        self.geoDet._do_exit = 1;

    def run(self):
        # check for replay mode
        if self.mode == 1:
            self.geoDet.replayFile(self.replayFile)
        else:          
            signal.signal(signal.SIGINT, self.sigint)
            try:
                self.serial.port = self.config.get('SERIAL','port')
                self.serial.baudrate = int(self.config.get('SERIAL','rate', fallback=4800))
            except:
                print("Error: Serial port parameters not provided! Pass --port parameter.", file=sys.stderr)
                exit(1)
            
            self.geoDet.mode = 1 # set cli mode for no idle state
            self.geoDet.state = 1 # skip idle and right to serial open
            self.geoDet.run()
            
        # store any new settings from cli
        self.writeSettings()
        
    def geoCB(self, msg):
        pass
 
if __name__ == '__main__':
    parser = OptionParser()
    parser.add_option("-p", "--port", dest="port",
                    help="GPS serial port")
    parser.add_option("-r", "--rate", dest="rate",type="int",
                    help="GPS serial rate")
    parser.add_option("-n", "--nmea", dest="nmeaFile",
                    help="NMEA data file for replay processing")
    parser.add_option("-b", "--boundary", dest="bndfile",
                    help="Boundary KML file or directory (default: ./boundaries)")
    #parser.add_option("-l", "--log", dest="logFile",
    #                 help="Log filename root, creates filename.log and filename.nmea")
    #parser.add_option("-v", "--verbose", dest="verbose",
    #                 action="store_true", default=False,
    #                 help="Verbose output data")

    (opts, args) = parser.parse_args()
      
         
    app = geoCLI(opts)
    app.run()
