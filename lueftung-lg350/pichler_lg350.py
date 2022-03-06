#!/usr/bin/env python3

import minimalmodbus

from pichler_registers import pichler_input_registers

import time
import argparse

class PichlerLG350(minimalmodbus.Instrument):
    def __init__(self, portname, slaveaddress=20, debug=False):
        minimalmodbus.Instrument.__init__(self, port=portname, slaveaddress=slaveaddress, debug=debug)  
        self.serial.parity =  minimalmodbus.serial.PARITY_EVEN

    def read_input_register(self, reg):
        return self.read_register(reg, 0, functioncode=4)
    
    def read_holding_register(self, reg):
        return self.read_register(reg, 0, functioncode=3)
    
    def get_all_input_registers(self):
        results = {}
        for name, params in pichler_input_registers.items():
            if params[3] == True:
                value = self.read_input_register(params[0])
                value += params[1]
                value *= params[2]
                results.update({name: value})
        return results

    def dump_all_input_registers(self):
        print("all input registers:")
        for i in range(120):
            value = self.read_input_register(i)
            print("reg {0} = {1}".format(i, value))
            time.sleep(0.25)

    def dump_all_holding_registers(self):
        print("all holding registers:")
        for i in range(120):
            value = self.read_holding_register(i)
            print("reg {0} = {1}".format(i, value))
            time.sleep(0.25)

    @property
    def luftstufe(self):
        value = self.read_holding_register(2)
        return value

    @luftstufe.setter
    def luftstufe(self, value):
        value = int(value)
        if value >= 0 and value < 4:
            self.write_register(2, value)
        else:
            print("luftstufe out of range")
            
    def get_errors(self):
        for i in range(60,80):
            print("{0}:Z{1} = {2}".format(i, (i-59), self.read_input_register(i)))

if __name__ == "__main__":

    argparser = argparse.ArgumentParser()
    argparser.add_argument("-p", "--port", help="serial port for Modbus RTU", 
                           default='/dev/ttyUSB0', action='store')
    argparser.add_argument("--debug", help="Enable debug output for Modbus RTU",
                           action='store_true')
    argparser.add_argument("-l", "--luftstufe", help="Set luftstufe", 
                           action='store')
    argparser.add_argument("-t", "--test", help="Enable Test functions",
                           action='store_true')
    argparser.add_argument("-dh", "--dump_holding", help="Dump Modbus holding registers",
                           action='store_true')
    argparser.add_argument("-di", "--dump_input", help="Dump Modbus input registers",
                           action='store_true')

    args = argparser.parse_args()
    
    lg350 = PichlerLG350(args.port, debug=args.debug)

    if args.luftstufe:
        print("Setting luftstufe to {0}".format(args.luftstufe))
        lg350.luftstufe = args.luftstufe

    regs = lg350.get_all_input_registers()
    print(regs)

    lg350.get_errors()

    if args.dump_holding:
        lg350.dump_all_holding_registers()

    if args.dump_input:
        lg350.dump_all_input_registers()

    if args.test:
        print(lg350.read_input_register(34)) 
        print(lg350.luftstufe)
 
