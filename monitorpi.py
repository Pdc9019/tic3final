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
import signal

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
                temperature REAL,
                humidity REAL,
                temp_avg REAL,
                temp_max REAL,
                temp_min REAL,
                hum_avg REAL,
                hum_max REAL,
                hum_min REAL,
                mode INTEGER NOT NULL
            )
        ''')
        self.conn.commit()

    def insert_data(self, timestamp, temperature, humidity, temp_avg=None, temp_max=None, temp_min=None,
                    hum_avg=None, hum_max=None, hum_min=None, mode=1):
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT INTO SensorData (timestamp, temperature, humidity, temp_avg, temp_max, temp_min,
                                    hum_avg, hum_max, hum_min, mode)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (timestamp, temperature, humidity, temp_avg, temp_max, temp_min, hum_avg, hum_max, hum_min, mode))
        self.conn.commit()

    def fetch_last_data(self, limit=20):
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT timestamp, temperature, humidity, temp_avg, temp_max, temp_min,
                   hum_avg, hum_max, hum_min, mode FROM SensorData
            ORDER BY id DESC LIMIT ?
        ''', (limit,))
        return cursor.fetchall()[::-1]  # Revertir para orden cronologico

# Clase para el servidor TCP
class TCPServer(threading.Thread):
    def __init__(self, data_queue):
        threading.Thread.__init__(self)
        self.data_queue = data_queue
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # Permitir reutilización de la dirección
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((SERVER_IP, SERVER_PORT))
        self.server_socket.listen(1)
        self.running = True
        self.client_socket = None
        self.client_lock = threading.Lock()

    def run(self):
        print(f"Servidor TCP escuchando en {SERVER_IP}:{SERVER_PORT}")
        while self.running:
            try:
                client_socket, client_address = self.server_socket.accept()
                print(f"Conexión aceptada de {client_address}")
                with self.client_lock:
                    self.client_socket = client_socket
                threading.Thread(target=self.handle_client, args=(client_socket,)).start()
            except Exception as e:
                if self.running:
                    print(f"Error en accept(): {e}")
                break

    def handle_client(self, client_socket):
        buffer = ""
        while self.running:
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
                if self.running:
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
                # Ponemos los datos en la cola, mode=1 para datos en bruto
                self.data_queue.put((timestamp, temperature, humidity, None, None, None, None, None, None, 1))
                print(f"Datos recibidos: Temperatura={temperature}C, Humedad={humidity}%")
            except Exception as e:
                print(f"Error al procesar DATA: {e}")
        elif message.startswith("STATS"):
            try:
                parts = message.split()
                if len(parts) == 7:
                    _, temp_avg, temp_max, temp_min, hum_avg, hum_max, hum_min = parts
                    temp_avg = float(temp_avg)
                    temp_max = float(temp_max)
                    temp_min = float(temp_min)
                    hum_avg = float(hum_avg)
                    hum_max = float(hum_max)
                    hum_min = float(hum_min)
                    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    # Ponemos los datos en la cola, mode=2 para datos procesados
                    self.data_queue.put((timestamp, None, None, temp_avg, temp_max, temp_min, hum_avg, hum_max, hum_min, 2))
                    print(f"Datos procesados recibidos:")
                    print(f"  Temp Promedio={temp_avg}C, Temp Max={temp_max}C, Temp Min={temp_min}C")
                    print(f"  Hum Promedio={hum_avg}%, Hum Max={hum_max}%, Hum Min={hum_min}%")
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
        with self.client_lock:
            if self.client_socket:
                try:
                    self.client_socket.shutdown(socket.SHUT_RDWR)
                    self.client_socket.close()
                except Exception as e:
                    print(f"Error al cerrar el socket del cliente: {e}")
                self.client_socket = None
        try:
            self.server_socket.shutdown(socket.SHUT_RDWR)
        except Exception as e:
            print(f"Error al cerrar el socket del servidor: {e}")
        self.server_socket.close()

# Clase principal de la interfaz gráfica
class TemperatureHumidityMonitorApp(QtWidgets.QMainWindow):
    def __init__(self, db, server, data_queue):
        super().__init__()
        self.db = db
        self.server = server
        self.data_queue = data_queue
        self.setWindowTitle("Monitor de Temperatura y Humedad")
        self.setGeometry(100, 100, 1000, 600)  # Aumentamos el ancho para acomodar nuevos elementos

        # Widget principal
        self.central_widget = QtWidgets.QWidget()
        self.setCentralWidget(self.central_widget)

        # Layout principal dividido en dos columnas
        self.main_layout = QtWidgets.QHBoxLayout(self.central_widget)

        # Layout izquierdo para los valores numéricos y controles
        self.left_layout = QtWidgets.QVBoxLayout()

        # Grupo para mostrar lecturas numéricas
        self.sensorGroup = QtWidgets.QGroupBox("Lecturas de Temperatura y Humedad")
        self.sensorLayout = QtWidgets.QGridLayout()  # Cambiamos a GridLayout para acomodar más elementos

        # LCDs para mostrar valores de temperatura y humedad
        self.n1Temperatura = QtWidgets.QLCDNumber()
        self.n1Temperatura.setSegmentStyle(QtWidgets.QLCDNumber.Flat)
        self.n2Humedad = QtWidgets.QLCDNumber()
        self.n2Humedad.setSegmentStyle(QtWidgets.QLCDNumber.Flat)

        # Etiquetas y LCDs para valores promedio, máximo y mínimo
        self.temp_avg_label = QtWidgets.QLabel("Temp Promedio (C)")
        self.temp_avg_display = QtWidgets.QLCDNumber()
        self.temp_max_label = QtWidgets.QLabel("Temp Máxima (C)")
        self.temp_max_display = QtWidgets.QLCDNumber()
        self.temp_min_label = QtWidgets.QLabel("Temp Mínima (C)")
        self.temp_min_display = QtWidgets.QLCDNumber()

        self.hum_avg_label = QtWidgets.QLabel("Hum Promedio (%)")
        self.hum_avg_display = QtWidgets.QLCDNumber()
        self.hum_max_label = QtWidgets.QLabel("Hum Máxima (%)")
        self.hum_max_display = QtWidgets.QLCDNumber()
        self.hum_min_label = QtWidgets.QLabel("Hum Mínima (%)")
        self.hum_min_display = QtWidgets.QLCDNumber()

        # Añadir los LCDs y etiquetas al layout del grupo
        self.sensorLayout.addWidget(QtWidgets.QLabel("Temperatura Actual (C)"), 0, 0)
        self.sensorLayout.addWidget(self.n1Temperatura, 0, 1)
        self.sensorLayout.addWidget(QtWidgets.QLabel("Humedad Actual (%)"), 1, 0)
        self.sensorLayout.addWidget(self.n2Humedad, 1, 1)

        self.sensorLayout.addWidget(self.temp_avg_label, 2, 0)
        self.sensorLayout.addWidget(self.temp_avg_display, 2, 1)
        self.sensorLayout.addWidget(self.temp_max_label, 3, 0)
        self.sensorLayout.addWidget(self.temp_max_display, 3, 1)
        self.sensorLayout.addWidget(self.temp_min_label, 4, 0)
        self.sensorLayout.addWidget(self.temp_min_display, 4, 1)

        self.sensorLayout.addWidget(self.hum_avg_label, 5, 0)
        self.sensorLayout.addWidget(self.hum_avg_display, 5, 1)
        self.sensorLayout.addWidget(self.hum_max_label, 6, 0)
        self.sensorLayout.addWidget(self.hum_max_display, 6, 1)
        self.sensorLayout.addWidget(self.hum_min_label, 7, 0)
        self.sensorLayout.addWidget(self.hum_min_display, 7, 1)

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

        # Añadir la sección de la izquierda al layout principal
        self.main_layout.addLayout(self.left_layout)

        # Área de gráficos en la sección derecha (dos gráficos: temperatura y humedad)
        self.figure, self.axs = plt.subplots(2, 1, figsize=(8, 10), sharex=True)
        self.canvas = FigureCanvas(self.figure)
        self.main_layout.addWidget(self.canvas, stretch=3)

        # Timer para procesar la cola y actualizar los datos automáticamente cada 2 segundos
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.process_data_queue)
        self.timer.start(2000)  # Actualizar cada 2 segundos

        # Actualizar los datos inicialmente al iniciar la aplicación
        self.actualizar_datos()

        # Variables para almacenar los valores internos
        self.internal_temps = []
        self.internal_hums = []

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
                data = self.data_queue.get_nowait()
                timestamp = data[0]
                mode = data[-1]
                if mode == 1:
                    # Datos en bruto
                    temperature = data[1]
                    humidity = data[2]
                    # Añadir a las listas internas
                    self.internal_temps.append(temperature)
                    self.internal_hums.append(humidity)
                    # Limitar el tamaño de las listas internas
                    if len(self.internal_temps) > 100:
                        self.internal_temps.pop(0)
                    if len(self.internal_hums) > 100:
                        self.internal_hums.pop(0)
                    # Insertar en la base de datos
                    self.db.insert_data(timestamp, temperature, humidity, mode=1)
                elif mode == 2:
                    # Datos procesados
                    temp_avg = data[3]
                    temp_max = data[4]
                    temp_min = data[5]
                    hum_avg = data[6]
                    hum_max = data[7]
                    hum_min = data[8]
                    # Insertar en la base de datos
                    self.db.insert_data(timestamp, None, None, temp_avg, temp_max, temp_min,
                                        hum_avg, hum_max, hum_min, mode=2)
                    # Mostrar los valores enviados por el ESP32
                    self.temp_avg_display.display(temp_avg)
                    self.temp_max_display.display(temp_max)
                    self.temp_min_display.display(temp_min)
                    self.hum_avg_display.display(hum_avg)
                    self.hum_max_display.display(hum_max)
                    self.hum_min_display.display(hum_min)
            except queue.Empty:
                break
        # Después de procesar los datos, actualiza la interfaz
        self.actualizar_datos()

    def actualizar_datos(self):
        # Obtener los datos de la base de datos
        data_list = self.db.fetch_last_data(20)  # Obtener los últimos 20 datos

        # Actualizar los valores de los LCDs
        if data_list:
            for data in data_list:
                mode = data[-1]
                if mode == 1:
                    # Datos en bruto
                    self.n1Temperatura.display(data[1])
                    self.n2Humedad.display(data[2])
                elif mode == 2:
                    # Datos procesados (ya mostrados en process_data_queue)
                    pass

            # Calcular valores internos promedio, máximo y mínimo
            if self.internal_temps:
                internal_temp_avg = sum(self.internal_temps) / len(self.internal_temps)
                internal_temp_max = max(self.internal_temps)
                internal_temp_min = min(self.internal_temps)

                self.temp_avg_label.setText(f"Temp Promedio (C) (Int: {internal_temp_avg:.2f})")
                self.temp_max_label.setText(f"Temp Máxima (C) (Int: {internal_temp_max:.2f})")
                self.temp_min_label.setText(f"Temp Mínima (C) (Int: {internal_temp_min:.2f})")

            if self.internal_hums:
                internal_hum_avg = sum(self.internal_hums) / len(self.internal_hums)
                internal_hum_max = max(self.internal_hums)
                internal_hum_min = min(self.internal_hums)

                self.hum_avg_label.setText(f"Hum Promedio (%) (Int: {internal_hum_avg:.2f})")
                self.hum_max_label.setText(f"Hum Máxima (%) (Int: {internal_hum_max:.2f})")
                self.hum_min_label.setText(f"Hum Mínima (%) (Int: {internal_hum_min:.2f})")

            # Actualizar gráficos
            self.graficar_datos(data_list)

    def graficar_datos(self, data_list):
        # Limpiar los ejes antes de volver a dibujar
        for ax in self.axs:
            ax.clear()

        if not data_list:
            print("No hay datos disponibles para graficar.")
            self.canvas.draw()
            return

        # Preparar datos para graficar (temperatura y humedad)
        timestamps = []
        temperaturas = []
        humedades = []

        for entry in data_list:
            timestamp = datetime.datetime.strptime(entry[0], "%Y-%m-%d %H:%M:%S")
            mode = entry[-1]
            if mode == 1:
                # Datos en bruto
                temp = entry[1]
                hum = entry[2]
            elif mode == 2:
                # Datos procesados (usamos el promedio)
                temp = entry[3]
                hum = entry[6]
            else:
                continue
            timestamps.append(timestamp)
            temperaturas.append(temp)
            humedades.append(hum)

        # Crear subplots
        self.axs[0].plot(timestamps, temperaturas, label='Temperatura (C)', color='r', marker='o')
        self.axs[0].set_ylabel('Temperatura (C)')
        self.axs[0].legend()
        self.axs[0].grid(True)

        self.axs[1].plot(timestamps, humedades, label='Humedad (%)', color='b', marker='o')
        self.axs[1].set_ylabel('Humedad (%)')
        self.axs[1].legend()
        self.axs[1].grid(True)

        # Formato de fechas en el eje x
        self.axs[1].xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
        self.figure.autofmt_xdate()

        self.figure.tight_layout()
        self.canvas.draw()

    def closeEvent(self, event):
        # Al cerrar la ventana, detener el servidor
        self.server.stop()
        event.accept()

if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)

    # Verificar si el puerto está en uso
    def is_port_in_use(port):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return s.connect_ex(('localhost', port)) == 0

    if is_port_in_use(SERVER_PORT):
        print(f"El puerto {SERVER_PORT} ya está en uso. Por favor, cierra otras instancias del programa.")
        sys.exit(1)

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

    # Manejar el cierre del programa con señales
    def signal_handler(sig, frame):
        print("Interrupción recibida, cerrando el servidor...")
        server.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)

    try:
        sys.exit(app.exec_())
    except SystemExit:
        print("Cerrando aplicación...")
    finally:
        server.stop()
