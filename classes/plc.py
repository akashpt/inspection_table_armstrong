from pymodbus.client.sync import ModbusTcpClient

PLC_IP = "192.168.1.5"
PLC_PORT = 502
UNIT_ID = 1

D0_ADDRESS = 0        # meter length
D512_ADDRESS = 512    # machine status
D514_ADDRESS = 514    # reset defect 


class PLCController:
    def __init__(self):
        self.client = None
        self.connected = False

    def connect(self):
        # return True
        try:
            if self.client is not None and self.connected:
                return True
 
            self.client = ModbusTcpClient(PLC_IP, port=PLC_PORT, timeout=1)

            if self.client.connect():
                self.connected = True
                print("✅ PLC CONNECTED")
                return True

            self.connected = False
            self.client = None
            print("❌ PLC NOT CONNECTED")
            return False

        except Exception as e:
            self.connected = False
            self.client = None
            print("PLC connect error:", e)
            return False

    def ensure_connected(self):
        if self.client is not None and self.connected:
            return True

        return self.connect()

    def read_register(self, address):
        try:
            if not self.ensure_connected():
                return None

            resp = self.client.read_holding_registers(
                address,
                1,
                unit=UNIT_ID
            )

            if resp is None or resp.isError():
                self.connected = False
                return None

            return resp.registers[0]

        except Exception as e:
            self.connected = False
            print(f"PLC read error D{address}:", e)
            return None

    def write_register(self, address, value):
        try:
            if not self.ensure_connected():
                return False

            resp = self.client.write_register(
                address,
                int(value),
                unit=UNIT_ID
            )

            if resp is None or resp.isError():
                self.connected = False
                return False

            print(f"✅ PLC WRITE D{address} = {value}")
            return True

        except Exception as e:
            self.connected = False
            print(f"PLC write error D{address}:", e)
            return False

    def machine_status(self):
        value = self.read_register(D512_ADDRESS)

        if value is None:
            print("Machine Not Connected")
            return None

        if value == 1:
            print("Machine ON")
        elif value == 0:
            print("Machine OFF")
        else:
            print("Machine unknown status:", value)

        return value

    def read_length(self):
        return self.read_register(D0_ADDRESS)

    def stop_machine(self):
        return self.write_register(D514_ADDRESS, 1)

    # def reset_stop(self):
    #     return self.write_register(D514_ADDRESS, 0)
    def reset_stop(self):
        try:
            print(f"➡️ PLC reset_stop: writing register {D514_ADDRESS} = 0")

            result = self.write_register(
                D514_ADDRESS,
                0
            )

            print("➡️ write_register result:", result)

            return result

        except Exception as error:
            print("❌ reset_stop error:", error)
            return False

    def close(self):
        try:
            if self.client is not None:
                self.client.close()
        except Exception:
            pass

        self.client = None
        self.connected = False
        print("PLC closed")
