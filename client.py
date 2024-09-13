from socket import socket, AF_INET, SOCK_DGRAM, error, SOCK_STREAM
import logging
from time import sleep
import keyboard
import qrcode


logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)


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


def process_data(data):
    """
    Process the received data. This simulates typing the data with a delay between each keystroke.
    """
    logging.info(f"Received data: {data}")

    try:
        keyboard.write(data)

        keyboard.press_and_release('enter')

    except Exception as e:
        logging.error(f"Error processing data: {e}")
        return


def start_server():
    """
    Start the TCP server to listen for incoming connections.
    """
    with socket(AF_INET, SOCK_STREAM) as server_socket:
        server_socket.bind((server_ip, server_port))
        server_socket.listen(5)
        logging.info(f"Server started and listening on {server_ip}:{server_port}")

        while True:
            try:
                client_socket, client_address = server_socket.accept()
                with client_socket:
                    logging.info(f"Connection from {client_address}")

                    while True:
                        data = client_socket.recv(1024)
                        if not data:
                            break

                        data = data.decode('utf-8')
                        process_data(data)

            except Exception as e:
                logging.error(f"Error handling connection: {e}")
                sleep(1)
                continue


def generate_qr_code(data: str):
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(data)
    qr.make(fit=True)

    qr_matrix = qr.get_matrix()

    return qr_matrix


def print_qr_code(matrix):
    for row in matrix:
        line = ""
        for col in row:
            if col:
                line += "██"
            else:
                line += "  "
        print(line)


if __name__ == "__main__":
    server_ip = get_ipv4_address()

    qr_data = f"Change;{server_ip}"
    qr_matr = generate_qr_code(qr_data, 'qr_code.png')
    print_qr_code(qr_matr)

    server_port = 15678

    start_server()