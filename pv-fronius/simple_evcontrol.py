#!/usr/bin/env python3

from fronius_gen24 import *
from pyfritzhome import Fritzhome
from influxdb_client import influxdb_cli
import paho.mqtt.client as paho

from devices import *

import time
import sys
import statistics

gen24 = SymoGen24(ipaddr=gen24_ip)

if gen24 is None:
    print("Gen24 don't like to talk to us")
    sys.exit(1)

fritzbox = Fritzhome(fritz_ip, fritz_user, fritz_pw)
fritzbox.login()
fritzbox.update_devices()
evswitch = fritzbox.get_device_by_ain(fritz_evswitch)

change_state = 0

influxdb = influxdb_cli(influxdb_ip, influxdb_user, influxdb_pw, influxdb_db)
influxdb_table = 'ev_golf'    

def on_connect(client, userdata, flags, rc):
    print("Connection returned result: " + str(rc))
    client.subscribe("pentling/ev_golf/change_state", 1)

# The callback for when a PUBLISH message is received from the server.
def on_message(client, userdata, msg):
    global change_state
    # print(msg.topic+": {0}".format(int(msg.payload)) )
    if msg.topic == "pentling/ev_golf/change_state":
        if int(msg.payload) >= 0 and int(msg.payload) <= 99:
            print("MQTT Change state {0}".format(msg.payload))
            change_state = int(msg.payload)

mqtt= paho.Client()
mqtt.on_connect = on_connect
mqtt.on_message = on_message
mqtt.connect(mqtt_ip, mqtt_port)
mqtt.loop_start()

class evcontrol:
    def __init__(self, evswitch, gen24, influxdb):
        self.evswitch = evswitch
        self.gen24 = gen24
        self.influxdb = influxdb
        
        self.power_available = [0.0, 0.0, 0.0, 0.0, 0.0]
        self.power_available_len = len(self.power_available)
        self.opmode = self.state_max_auto_charging
        self.debugstate = 0
        
        self.update_values()
        self.do_writestatus()
        
    def change_state(self, newstate):
        print("set new state: {0}".format(newstate))
        if newstate == 1:
            self.opmode = self.state_max_auto_charging
        elif newstate == 2:
            self.opmode = self.state_min_auto_charging
        elif newstate == 21:
            self.opmode = self.state_force_on_charging
        elif newstate == 22:
            self.opmode = self.state_force_off_charging
        else:
            self.opmode = self.state_max_auto_charging
    
    def state_max_auto_charging(self):
        
        self.update_values()
                
        if self.house_battery_soc < 50:
            self.power_available.append(0.0)
            print("-> House battery lower than 50%, don't do anything")
            self.debugstate = 2

        elif self.power_to_grid < -100.0:
            self.power_available.append(0.0)
            print("-> Getting significant power from Grid, no excess power available for EV")
            self.debugstate = 3

        elif self.power_generated > 2500.0:
            if self.power_generated > self.power_consumption - self.power_to_ev:
                self.power_available.append(self.power_generated - (self.power_consumption - self.power_to_ev))
                print("-> PV-Generating at least more than 2500W")
                self.debugstate = 5
            else:
                self.power_available.append(0.0)
                print("-> PV-Generating at least more than 2500W, but house takes it already")
                self.debugstate = 6
        else:
            self.power_available.append(0.0)
            print("Less than 2000W generated")
            self.debugstate = 7

        self.do_switching(6500.0)
        self.do_writestatus()

    
    def state_min_auto_charging(self):
        self.update_values()
                
        if self.house_battery_soc < 95:
            self.power_available.append(0.0)
            print("-> House battery lower than 95%, don't do anything")
            self.debugstate = 12

        elif self.power_to_grid < -100.0:
            self.power_available.append(0.0)
            print("-> Getting significant power from Grid, no excess power available for EV")
            self.debugstate = 13

        elif self.power_generated > 6500.0:
            if self.power_generated > self.power_consumption - self.power_to_ev:
                self.power_available.append(self.power_generated - (self.power_consumption - self.power_to_ev))
                print("-> PV-Generating at least more than 2000W, taking out 150W for the rest of the house")
                self.debugstate = 15
            else:
                self.power_available.append(0.0)
                print("-> PV-Generating at least more than 2000W, but house takes it already")
                self.debugstate = 16
        else:
            self.power_available.append(0.0)
            print("Less than 2000W generated")
            self.debugstate = 17

        self.do_switching(2200.0)
        self.do_writestatus()
    
    
    def state_force_on_charging(self):
        self.debugstate = 21
        self.update_values()
        self.power_available = [2500.0]
        self.do_switching(1)
        self.do_writestatus()
    
    
    def state_force_off_charging(self):
        self.debugstate = 22
        self.update_values()
        self.power_available = [0.0]
        self.do_switching(100000)
        self.do_writestatus()
    
    
    def update_values(self):
        influxdb_table = 'ev_golf'    

        self.power_to_grid = self.gen24.read_data("Meter_Power_Total") * -1.0
        self.power_consumption = self.gen24.read_calculated_value("Consumption_Sum") 
        self.power_generated = self.gen24.read_calculated_value("PV_Power")
        self.power_to_ev = (self.evswitch.get_switch_power()/1000)
        self.energy_to_ev = (self.evswitch.get_switch_energy()/1000)
        self.house_battery_soc = self.gen24.read_data("Battery_SoC")
        
        print("pwr_gen: {0}, pwr_grid: {1}, pwr_consum: {2}, pwr_ev: {3}".format(self.power_generated, self.power_to_grid, self.power_consumption, self.power_to_ev))

        self.influxdb.write_sensordata(influxdb_table, 'power_to_ev', self.power_to_ev)
        self.influxdb.write_sensordata(influxdb_table, 'energy_to_ev', self.energy_to_ev)


    def do_writestatus(self):
        influxdb_table = 'ev_golf'    

        self.influxdb.write_sensordata(influxdb_table, 'debugstate', self.debugstate)
        self.influxdb.write_sensordata(influxdb_table, 'power_available', statistics.fmean(self.power_available))

        ev_switch_state = int(self.evswitch.get_switch_state())
        ev_switch_temperature = self.evswitch.get_temperature()
        self.influxdb.write_sensordata(influxdb_table, 'ev_switch_state', ev_switch_state)
        self.influxdb.write_sensordata(influxdb_table, 'ev_switch_temperature', ev_switch_temperature)


    def do_switching(self, limit):
        
        print("Values in buffer")
        print(self.power_available)
        print("Average Power Available: {0} W".format(statistics.fmean(self.power_available)))

        while len(self.power_available) > self.power_available_len:
            self.power_available.pop(0)    
        if len(self.power_available) == 0:
            self.power_available = [0.0]
        
        if statistics.fmean(self.power_available) >= limit:
            print("Switch on")
            self.evswitch.set_switch_state_on()
        else:
            print("Switch off")
            self.evswitch.set_switch_state_off()

golfonso = evcontrol(evswitch, gen24, influxdb)

while True:
    
    if change_state > 0:
        golfonso.change_state(change_state)
        change_state = 0

    golfonso.opmode()

    time.sleep(120)

