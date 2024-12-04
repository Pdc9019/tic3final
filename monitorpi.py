import socket
import threading
import sqlite3
import datetime
import sys
import matplotlib
matplotlib.use('Qt5Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import queue

from PyQt5 import QtWidgets, QtCore
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas

# Configuraciones del Servidor TCP
SERVER_IP = "0.0.0.0"  # Escuchar en todas las interfaces
SERVER_PORT = 8888
BUFFER_SIZE = 1024

# Base de datos SQLite
DB_FILE = "sensor_data.db"

# Clase para manejar la base de datos
class DataBase:
    def __init__(self, db_file):
        self.conn = sqlite3.connect(db_file)
        self.create_table()

    def create_table(self):
        cursor = self.conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS SensorData (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                temperature REAL NOT NULL,
                humidity REAL NOT NULL
            )
        ''')
        self.conn.commit()

    def insert_data(self, timestamp, temperature, humidity):
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT INTO SensorData (timestamp, temperature, humidity)
            VALUES (?, ?, ?)
        ''', (timestamp, temperature, humidity))
        self.conn.commit()

    def fetch_last_data(self, limit=20):
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT timestamp, temperature, humidity FROM SensorData
            ORDER BY id DESC LIMIT ?
        ''', (limit,))
        return cursor.fetchall()[::-1]  # Revertir para orden cronologico

# Clase para el servidor TCP
class TCPServer(threading.Thread):
    def __init__(self, data_queue):
        threading.Thread.__init__(self)
        self.data_queue = data_queue
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.bind((SERVER_IP, SERVER_PORT))
        self.server_socket.listen(1)
        self.running = True
        self.client_socket = None
        self.client_lock = threading.Lock()

    def run(self):
        print(f"Servidor TCP escuchando en {SERVER_IP}:{SERVER_PORT}")
        while self.running:
            client_socket, client_address = self.server_socket.accept()
            print(f"Conexion aceptada de {client_address}")
            with self.client_lock:
                self.client_socket = client_socket
            threading.Thread(target=self.handle_client, args=(client_socket,)).start()

    def handle_client(self, client_socket):
        buffer = ""
        while True:
            try:
                data = client_socket.recv(BUFFER_SIZE)
                if not data:
                    break
                buffer += data.decode()
                while '\n' in buffer:
                    message, buffer = buffer.split('\n', 1)
                    message = message.strip()
                    if message:
                        self.process_message(message)
            except Exception as e:
                print(f"Error al manejar datos del cliente: {e}")
                break
        client_socket.close()
        with self.client_lock:
            if self.client_socket == client_socket:
                self.client_socket = None

    def process_message(self, message):
        # Procesar el mensaje basado en su tipo (DATA o STATS)
        if message.startswith("DATA"):
            try:
                _, temp_str, hum_str = message.split()
                temperature = float(temp_str)
                humidity = float(hum_str)
                timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                # En lugar de insertar en la base de datos, ponemos los datos en la cola
                self.data_queue.put((timestamp, temperature, humidity))
                print(f"Datos recibidos: Temperatura={temperature}C, Humedad={humidity}%")
            except Exception as e:
                print(f"Error al procesar DATA: {e}")
        elif message.startswith("STATS"):
            try:
                parts = message.split()
                if len(parts) == 7:
                    _, temp_avg, temp_max, temp_min, hum_avg, hum_max, hum_min = parts
                    # Puedes almacenar estos datos o mostrarlos
                    print(f"Datos procesados recibidos:")
                    print(f"  Temp Promedio={temp_avg}C, Temp Max={temp_max}C, Temp Min={temp_min}C")
                    print(f"  Hum Promedio={hum_avg}%, Hum Max={hum_max}%, Hum Min={hum_min}%")
                    # Por simplicidad, almacenamos el promedio en la base de datos
                    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    temperature = float(temp_avg)
                    humidity = float(hum_avg)
                    self.data_queue.put((timestamp, temperature, humidity))
                else:
                    print("Mensaje STATS con formato incorrecto")
            except Exception as e:
                print(f"Error al procesar STATS: {e}")
        else:
            print(f"Mensaje desconocido: {message}")

    def send_command(self, command):
        with self.client_lock:
            if self.client_socket:
                try:
                    self.client_socket.sendall(command.encode() + b'\n')
                    print(f"Comando enviado: {command}")
                except Exception as e:
                    print(f"Error al enviar comando: {e}")
            else:
                print("No hay cliente conectado para enviar comandos.")

    def stop(self):
        self.running = False
        self.server_socket.close()
        with self.client_lock:
            if self.client_socket:
                self.client_socket.close()

# Clase principal de la interfaz grafica
class TemperatureHumidityMonitorApp(QtWidgets.QMainWindow):
    def __init__(self, db, server, data_queue):
        super().__init__()
        self.db = db
        self.server = server
        self.data_queue = data_queue
        self.setWindowTitle("Monitor de Temperatura y Humedad")
        self.setGeometry(100, 100, 800, 600)

        # Widget principal
        self.central_widget = QtWidgets.QWidget()
        self.setCentralWidget(self.central_widget)

        # Layout principal dividido en dos columnas
        self.main_layout = QtWidgets.QHBoxLayout(self.central_widget)

        # Layout izquierdo para los valores numericos y controles
        self.left_layout = QtWidgets.QVBoxLayout()

        # Grupo para mostrar lecturas numericas
        self.sensorGroup = QtWidgets.QGroupBox("Lecturas de Temperatura y Humedad")
        self.sensorLayout = QtWidgets.QVBoxLayout()

        # LCDs para mostrar valores de temperatura y humedad
        self.n1Temperatura = QtWidgets.QLCDNumber()
        self.n1Temperatura.setSegmentStyle(QtWidgets.QLCDNumber.Flat)
        self.n2Humedad = QtWidgets.QLCDNumber()
        self.n2Humedad.setSegmentStyle(QtWidgets.QLCDNumber.Flat)

        # Añadir los LCDs al layout del grupo
        self.sensorLayout.addWidget(QtWidgets.QLabel("Temperatura (C)"))
        self.sensorLayout.addWidget(self.n1Temperatura)
        self.sensorLayout.addWidget(QtWidgets.QLabel("Humedad (%)"))
        self.sensorLayout.addWidget(self.n2Humedad)

        self.sensorGroup.setLayout(self.sensorLayout)
        self.left_layout.addWidget(self.sensorGroup)

        # Añadir controles
        self.controlGroup = QtWidgets.QGroupBox("Controles")
        self.controlLayout = QtWidgets.QVBoxLayout()

        self.startButton = QtWidgets.QPushButton("Iniciar Monitoreo")
        self.startButton.clicked.connect(self.start_monitoring)
        self.stopButton = QtWidgets.QPushButton("Detener Monitoreo")
        self.stopButton.clicked.connect(self.stop_monitoring)

        self.mode1Button = QtWidgets.QPushButton("Modo 1 (Datos en Bruto)")
        self.mode1Button.clicked.connect(self.set_mode1)
        self.mode2Button = QtWidgets.QPushButton("Modo 2 (Datos Procesados)")
        self.mode2Button.clicked.connect(self.set_mode2)

        self.freqLabel = QtWidgets.QLabel("Frecuencia de Muestreo (ms):")
        self.freqInput = QtWidgets.QSpinBox()
        self.freqInput.setRange(100, 10000)
        self.freqInput.setValue(1000)
        self.freqButton = QtWidgets.QPushButton("Establecer Frecuencia")
        self.freqButton.clicked.connect(self.set_frequency)

        self.windowLabel = QtWidgets.QLabel("Ventana de Tiempo (ms):")
        self.windowInput = QtWidgets.QSpinBox()
        self.windowInput.setRange(1000, 60000)
        self.windowInput.setValue(5000)
        self.windowButton = QtWidgets.QPushButton("Establecer Ventana")
        self.windowButton.clicked.connect(self.set_window)

        # Añadir controles al layout
        self.controlLayout.addWidget(self.startButton)
        self.controlLayout.addWidget(self.stopButton)
        self.controlLayout.addWidget(self.mode1Button)
        self.controlLayout.addWidget(self.mode2Button)
        self.controlLayout.addWidget(self.freqLabel)
        self.controlLayout.addWidget(self.freqInput)
        self.controlLayout.addWidget(self.freqButton)
        self.controlLayout.addWidget(self.windowLabel)
        self.controlLayout.addWidget(self.windowInput)
        self.controlLayout.addWidget(self.windowButton)

        self.controlGroup.setLayout(self.controlLayout)
        self.left_layout.addWidget(self.controlGroup)

        # Añadir la seccion de la izquierda al layout principal
        self.main_layout.addLayout(self.left_layout)

        # Area de graficos en la seccion derecha (dos graficos: temperatura y humedad)
        self.figure, self.axs = plt.subplots(2, 1, figsize=(8, 10), sharex=True)
        self.canvas = FigureCanvas(self.figure)
        self.main_layout.addWidget(self.canvas, stretch=3)

        # Timer para procesar la cola y actualizar los datos automaticamente cada 2 segundos
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.process_data_queue)
        self.timer.start(2000)  # Actualizar cada 2 segundos

        # Actualizar los datos inicialmente al iniciar la aplicacion
        self.actualizar_datos()

    def start_monitoring(self):
        self.server.send_command("START")

    def stop_monitoring(self):
        self.server.send_command("STOP")

    def set_mode1(self):
        self.server.send_command("MODE1")

    def set_mode2(self):
        self.server.send_command("MODE2")

    def set_frequency(self):
        freq = self.freqInput.value()
        self.server.send_command(f"SET_FREQ {freq}")

    def set_window(self):
        window = self.windowInput.value()
        self.server.send_command(f"SET_WINDOW {window}")

    def process_data_queue(self):
        # Procesa todos los elementos en la cola
        while not self.data_queue.empty():
            try:
                timestamp, temperature, humidity = self.data_queue.get_nowait()
                # Inserta los datos en la base de datos
                self.db.insert_data(timestamp, temperature, humidity)
            except queue.Empty:
                break
        # Después de procesar los datos, actualiza la interfaz
        self.actualizar_datos()

    def actualizar_datos(self):
        # Obtener los datos de la base de datos
        data_list = self.db.fetch_last_data(20)  # Obtener los ultimos 20 datos

        # Actualizar los valores de los LCDs
        if data_list:
            ultimo_dato = data_list[-1]
            self.n1Temperatura.display(ultimo_dato[1])
            self.n2Humedad.display(ultimo_dato[2])

            # Actualizar graficos
            self.graficar_datos(data_list)

    def graficar_datos(self, data_list):
        # Limpiar los ejes antes de volver a dibujar
        for ax in self.axs:
            ax.clear()

        if not data_list:
            print("No hay datos disponibles para graficar.")
            self.canvas.draw()
            return

        # Preparar datos para graficar (dos graficos: temperatura y humedad)
        timestamps = [datetime.datetime.strptime(entry[0], "%Y-%m-%d %H:%M:%S") for entry in data_list]
        temperaturas = [entry[1] for entry in data_list]
        humedades = [entry[2] for entry in data_list]

        # Crear subplots
        self.axs[0].plot(timestamps, temperaturas, label='Temperatura (C)', color='r')
        self.axs[0].set_ylabel('Temperatura (C)')
        self.axs[0].legend()
        self.axs[0].grid(True)

        self.axs[1].plot(timestamps, humedades, label='Humedad (%)', color='b')
        self.axs[1].set_ylabel('Humedad (%)')
        self.axs[1].legend()
        self.axs[1].grid(True)

        # Formato de fechas en el eje x
        self.axs[1].xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
        self.figure.autofmt_xdate()

        self.figure.tight_layout()
        self.canvas.draw()

if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)

    # Inicializar la base de datos
    db = DataBase(DB_FILE)

    # Crear la cola para los datos
    data_queue = queue.Queue()

    # Iniciar el servidor TCP en un hilo separado
    server = TCPServer(data_queue)
    server.start()

    # Crear e iniciar la aplicación gráfica
    main_window = TemperatureHumidityMonitorApp(db, server, data_queue)
    main_window.show()

    # Manejar el cierre del programa
    try:
        sys.exit(app.exec_())
    except SystemExit:
        print("Cerrando aplicación...")
        server.stop()
