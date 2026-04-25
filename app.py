import asyncio
import argparse

from ble import DeviceLister, DeviceEnumerator, DeviceServiceConnector

def main():
    arg_parser = argparse.ArgumentParser(description='Scan BLE devices')
    arg_parser.add_argument('--device-enumerate', action='store_true', help='Enumerate specific device')
    arg_parser.add_argument('--scan-sec', help='Scan for number of seconds', default=0)
    arg_parser.add_argument('--notify-sec', help='Service notify processing number of seconds', default=0)
    arg_parser.add_argument('--device-address', help='Device MAC address to connect')
    arg_parser.add_argument('--service-uuid', help='Service UUID for characteristic data')
    arg_parser.add_argument('--decode-data', action='store_true', help='Decode the Watchdog service data, do not add for raw data')
    args = arg_parser.parse_args()

    scan_sec = 0
    if args.scan_sec and int(args.scan_sec) > 0:
        scan_sec = int(args.scan_sec)
    notify_sec = 0
    if args.notify_sec and int(args.notify_sec) > 0:
        notify_sec = int(args.notify_sec)

    try:
        if args.device_enumerate and args.device_address:
            asyncio.run(DeviceEnumerator(address=args.device_address, scan_sec=scan_sec).execute())
        elif args.device_address and args.service_uuid:
            asyncio.run(DeviceServiceConnector(address=args.device_address, scan_sec=scan_sec, notify_sec=notify_sec, service_uuid=args.service_uuid, decode_data=args.decode_data).execute())
        elif not args.device_enumerate:
            asyncio.run(DeviceLister(scan_sec=scan_sec).execute())
    except KeyboardInterrupt:
        print('Program interrupted by user (Ctrl+C). Shutting down')

if __name__ == '__main__':
    main()
