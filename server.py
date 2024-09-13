import asyncio
import os
from socket import socket, AF_INET, SOCK_DGRAM, error, SOCK_STREAM
import websockets
import json
import ipaddress
from base64 import b64decode
from typing import Dict, Any
import logging
import re

# Define the subnet range
subnet = ipaddress.ip_network("10.188.20.0/26")
buffer_queue = asyncio.Queue()

# Configure logging to include datetime
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

CONFIG_FILE = './config/config.json'
TCP_PORT = 15678  # TCP port for communication with the client


def update_config(serial_number: str, forward_ip: str):
    config = {}
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            config = json.load(f)

    config[serial_number] = forward_ip

    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=4)


def get_ipv4_address():
    try:
        # Create a socket object
        s = socket(AF_INET, SOCK_DGRAM)

        # Connect to a remote server (doesn't matter which server)
        s.connect(("8.8.8.8", 80))

        # Get the local IP address of the socket
        ip_address = s.getsockname()[0]

        return ip_address
    except error as e:
        return None


async def handle_proglove_data(websocket, path):
    client_ip = websocket.remote_address[0]

    if ipaddress.ip_address(client_ip) in subnet:
        if path == "/proglove":
            try:
                async for message in websocket:
                    try:
                        data = json.loads(message)
                        logging.debug(f"Received JSON data: {json.dumps(data, indent=4)}")
                        await buffer_queue.put(data)

                    except json.JSONDecodeError as e:
                        logging.error(f"Error decoding JSON: {e}")
                        error_message = {"status": "error", "message": "Invalid JSON"}
                        await websocket.send(json.dumps(error_message))
                    except Exception as e:
                        logging.error(f"Unexpected error: {e}")
                        error_message = {"status": "error", "message": "An unexpected error occurred"}
                        await websocket.send(json.dumps(error_message))
            except websockets.ConnectionClosed:
                logging.info(f"Client {client_ip} disconnected.")
        else:
            await websocket.close()
    else:
        await websocket.close()


def is_valid_change_command(data: str) -> bool:
    pattern = re.compile(r'^Change;(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$')
    return bool(pattern.match(data))


async def send_data_to_specific_client(serial_number: str, message: str):
    """
    Sends data only to the client associated with the provided serial_number in config.json.
    Includes reconnection and retry logic.
    """
    forward_ip = get_config(serial_number)

    if forward_ip:
        max_retries = 3
        retry_count = 0
        while retry_count < max_retries:
            try:
                reader, writer = await asyncio.open_connection(forward_ip, TCP_PORT)

                # Send the message
                writer.write(message.encode('utf-8'))
                await writer.drain()

                logging.info(f"Sent data to client {forward_ip}: {message}")

                # Close the connection
                writer.close()
                await writer.wait_closed()
                break

            except asyncio.TimeoutError:
                logging.error(f"Timeout when sending data to {forward_ip}. Retry {retry_count + 1}/{max_retries}.")
                retry_count += 1
            except Exception as e:
                logging.error(f"Error sending data to {forward_ip}: {e}")
                retry_count += 1

        if retry_count == max_retries:
            logging.error(f"Failed to send data to {forward_ip} after {max_retries} retries.")
    else:
        logging.error(f"No IP address found for serial_number: {serial_number}")


def get_config(serial_number: str) -> str | None:
    """
    Get the IP address associated with the given serial_number from config.json.
    """
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            config = json.load(f)
        return config.get(serial_number)
    return None


async def process_data_from_queue():
    """
    Continuously process data from the buffer queue in the background.
    """
    while True:
        data = await buffer_queue.get()
        scan_code = data.get('scan_code')
        device_serial = data.get('device_serial')

        logging.info(scan_code)

        if scan_code and is_valid_change_command(scan_code):
            change_forward_ip(data, scan_code)

        else:
            if data.get("event_type") == "scan":
                response = handle_scan_event(data)
                await send_data_to_specific_client(device_serial, scan_code)

            elif data.get("event_type") == "errors":
                response = handle_error_event(data)
            else:
                response = b"Unknown event type"

            logging.debug(f"Processed message: {response}")
            buffer_queue.task_done()


def change_forward_ip(data, message):
    if 'Change;' in message:
        qr_data = message.strip().split(';')
        if len(qr_data) == 2 and qr_data[0] == 'Change':
            forward_ip = qr_data[1]
            device_serial = data.get('device_serial')
            if device_serial:
                update_config(device_serial, forward_ip)
                logging.info(f"Config updated: {device_serial} -> {forward_ip}")


def handle_scan_event(event: Dict[str, Any]) -> bytes:
    """
    Handler to react to a scan stream event.
    """
    if "scan_bytes" not in event:
        return b"Error: 'scan_bytes' not found in event"

    try:
        raw_bytes = b64decode(event["scan_bytes"].encode())
        logging.debug(f"Decoded scan bytes: {raw_bytes}")
        return b"Success"
    except Exception as e:
        logging.error(f"Error processing scan event: {str(e)}")
        return f"Error processing scan event: {str(e)}".encode()


def handle_error_event(event: Dict[str, Any]) -> bytes:
    """
    Handler to react to an error event.
    """
    error_message = event.get("error_message", "Unknown error")
    logging.error(f"Error received: {error_message}")
    return f"Error event processed: {error_message}".encode()


async def main():
    local_ip = get_ipv4_address()
    logging.info(f"Starting server on IP {local_ip}:8765")

    # Start the background task to process the queue
    processing_task = asyncio.create_task(process_data_from_queue())

    # Start the WebSocket server with reconnection support
    while True:
        try:
            async with websockets.serve(handle_proglove_data, local_ip, 8765):
                logging.info("WebSocket server started. Awaiting connections...")
                await asyncio.Future()  # Keep the server running indefinitely
        except Exception as e:
            logging.error(f"WebSocket server error: {e}")
            logging.info("Restarting WebSocket server in 5 seconds...")
            await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())
