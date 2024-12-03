import socket
import threading
import sqlite3
import datetime
import sys
import matplotlib.pyplot as plt
from PyQt5 import QtWidgets, QtCore
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas

# Configuraciones del Servidor TCP
SERVER_IP = "192.168.4.1"
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

    def fetch_last_data(self, limit=10):
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT timestamp, temperature, humidity FROM SensorData
            ORDER BY id DESC LIMIT ?
        ''', (limit,))
        return cursor.fetchall()

# Clase para el servidor TCP
class TCPServer(threading.Thread):
    def __init__(self, db, update_callback):
        threading.Thread.__init__(self)
        self.db = db
        self.update_callback = update_callback
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.bind((SERVER_IP, SERVER_PORT))
        self.server_socket.listen(1)
        self.running = True

    def run(self):
        print(f"Servidor TCP escuchando en {SERVER_IP}:{SERVER_PORT}")
        while self.running:
            client_socket, client_address = self.server_socket.accept()
            print(f"Conexion aceptada de {client_address}")
            threading.Thread(target=self.handle_client, args=(client_socket,)).start()

    def handle_client(self, client_socket):
        while True:
            try:
                data = client_socket.recv(BUFFER_SIZE)
                if not data:
                    break
                temperature, humidity = map(float, data.decode().split(","))
                timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self.db.insert_data(timestamp, temperature, humidity)
                print(f"Datos recibidos: Temperatura={temperature}C, Humedad={humidity}%")
                self.update_callback()
            except Exception as e:
                print(f"Error al manejar datos del cliente: {e}")
                break
        client_socket.close()

    def stop(self):
        self.running = False
        self.server_socket.close()

# Clase principal de la interfaz grafica
class TemperatureHumidityMonitorApp(QtWidgets.QMainWindow):
    def __init__(self, db):
        super().__init__()
        self.db = db
        self.setWindowTitle("Monitor de Temperatura y Humedad")
        self.setGeometry(100, 100, 800, 600)

        # Widget principal
        self.central_widget = QtWidgets.QWidget()
        self.setCentralWidget(self.central_widget)

        # Layout principal dividido en dos columnas
        self.main_layout = QtWidgets.QHBoxLayout(self.central_widget)

        # Layout izquierdo para los valores numericos
        self.left_layout = QtWidgets.QVBoxLayout()

        # Grupo para mostrar lecturas numericas
        self.sensorGroup = QtWidgets.QGroupBox("Lecturas de Temperatura y Humedad")
        self.sensorLayout = QtWidgets.QVBoxLayout()

        # LCDs para mostrar valores de temperatura y humedad
        self.n1Temperatura = QtWidgets.QLCDNumber()
        self.n1Temperatura.setSegmentStyle(QtWidgets.QLCDNumber.Flat)
        self.n2Humedad = QtWidgets.QLCDNumber()
        self.n2Humedad.setSegmentStyle(QtWidgets.QLCDNumber.Flat)

        # Anadir los LCDs al layout del grupo
        self.sensorLayout.addWidget(QtWidgets.QLabel("Temperatura (C)"))
        self.sensorLayout.addWidget(self.n1Temperatura)
        self.sensorLayout.addWidget(QtWidgets.QLabel("Humedad (%)"))
        self.sensorLayout.addWidget(self.n2Humedad)

        self.sensorGroup.setLayout(self.sensorLayout)
        self.left_layout.addWidget(self.sensorGroup)

        # Anadir la seccion de la izquierda al layout principal
        self.main_layout.addLayout(self.left_layout)

        # Area de graficos en la seccion derecha (solo dos graficos: temperatura y humedad)
        self.figure, self.axs = plt.subplots(2, 1, figsize=(8, 10), sharex=True)
        self.canvas = FigureCanvas(self.figure)
        self.main_layout.addWidget(self.canvas, stretch=3)

        # Boton para actualizar los datos manualmente
        self.updateButton = QtWidgets.QPushButton("Actualizar Datos")
        self.updateButton.clicked.connect(self.actualizar_datos)
        self.left_layout.addWidget(self.updateButton)

        # Timer para actualizar los datos automaticamente cada 2 segundos
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.actualizar_datos)
        self.timer.start(2000)  # Actualizar cada 2 segundos

        # Actualizar los datos inicialmente al iniciar la aplicacion
        self.actualizar_datos()

    def actualizar_datos(self):
        # Obtener los datos de la base de datos
        data_list = self.db.fetch_last_data(10)

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

        # Preparar datos para graficar (solo dos graficos: temperatura y humedad)
        timestamps = [datetime.datetime.strptime(entry[0], "%Y-%m-%d %H:%M:%S") for entry in data_list]
        temperaturas = [entry[1] for entry in data_list]
        humedades = [entry[2] for entry in data_list]

        # Crear subplots
        self.axs[0].plot(timestamps, temperaturas, label='Temp (C)', color='r')
        self.axs[0].set_ylabel('Temp (C)')
        self.axs[0].legend()
        self.axs[0].grid(True)

        self.axs[1].plot(timestamps, humedades, label='Humedad (%)', color='b')
        self.axs[1].set_ylabel('Humedad (%)')
        self.axs[1].legend()
        self.axs[1].grid(True)

        self.figure.tight_layout()
        self.canvas.draw()

if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)

    # Inicializar la base de datos
    db = DataBase(DB_FILE)

    # Crear e iniciar la aplicacion grafica
    main_window = TemperatureHumidityMonitorApp(db)
    main_window.show()

    # Iniciar el servidor TCP en un hilo separado
    server = TCPServer(db, main_window.actualizar_datos)
    server.start()

    # Manejar el cierre del programa
    try:
        sys.exit(app.exec_())
    except SystemExit:
        print("Cerrando aplicacion...")
        server.stop()
