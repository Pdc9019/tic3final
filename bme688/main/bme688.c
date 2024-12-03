#include <float.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "driver/i2c.h"
#include "driver/uart.h"
#include "esp_log.h"
#include "esp_wifi.h"
#include "esp_event.h"
#include "nvs_flash.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "math.h"
#include "sdkconfig.h"
#include "lwip/sockets.h"

#define WIFI_SSID "monitor1"        // Nombre de la red WiFi creada por la Raspberry Pi
#define WIFI_PASS "hola1234"    // Contraseña de la red WiFi

#define CONCAT_BYTES(msb, lsb) (((uint16_t)msb << 8) | (uint16_t)lsb)

#define BUF_SIZE (128)       // buffer size
#define TXD_PIN 1            // UART TX pin
#define RXD_PIN 3            // UART RX pin
#define UART_NUM UART_NUM_0  // UART port number
#define BAUD_RATE 115200     // Baud rate
#define M_PI 3.14159265358979323846

#define I2C_MASTER_SCL_IO GPIO_NUM_22  // GPIO pin
#define I2C_MASTER_SDA_IO GPIO_NUM_21  // GPIO pin
#define I2C_MASTER_FREQ_HZ 10000
#define BME_ESP_SLAVE_ADDR 0x76
#define WRITE_BIT 0x0
#define READ_BIT 0x1
#define ACK_CHECK_EN 0x0
#define EXAMPLE_I2C_ACK_CHECK_DIS 0x0
#define ACK_VAL 0x0
#define NACK_VAL 0x1

#define SERVER_IP "192.168.4.1" // Dirección IP de la Raspberry Pi
#define SERVER_PORT 8888        // Puerto donde está escuchando el servidor en la Raspberry Pi

esp_err_t ret = ESP_OK;

void wifi_init_sta(void) {
    esp_netif_init();
    esp_event_loop_create_default();
    esp_netif_create_default_wifi_sta();
    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    esp_wifi_init(&cfg);

    wifi_config_t wifi_config = {
        .sta = {
            .ssid = WIFI_SSID,
            .password = WIFI_PASS,
        },
    };

    esp_wifi_set_mode(WIFI_MODE_STA);
    esp_wifi_set_config(ESP_IF_WIFI_STA, &wifi_config);
    esp_wifi_start();

    esp_wifi_connect();
    ESP_LOGI("wifi_init_sta", "Conectando al AP SSID: %s", WIFI_SSID);
}

void tcp_client_task(void *pvParameters) {
    char rx_buffer[128];
    char host_ip[] = SERVER_IP;
    int addr_family = 0;
    int ip_protocol = 0;

    while (1) {
        struct sockaddr_in dest_addr;
        dest_addr.sin_addr.s_addr = inet_addr(host_ip);
        dest_addr.sin_family = AF_INET;
        dest_addr.sin_port = htons(SERVER_PORT);
        addr_family = AF_INET;
        ip_protocol = IPPROTO_IP;

        int sock = socket(addr_family, SOCK_STREAM, ip_protocol);
        if (sock < 0) {
            ESP_LOGE("TCP Client", "Unable to create socket: errno %d", errno);
            vTaskDelay(2000 / portTICK_PERIOD_MS);
            continue;
        }
        ESP_LOGI("TCP Client", "Socket creado, conectando a %s:%d", host_ip, SERVER_PORT);

        int err = connect(sock, (struct sockaddr *)&dest_addr, sizeof(dest_addr));
        if (err != 0) {
            ESP_LOGE("TCP Client", "Socket no pudo conectarse: errno %d", errno);
            close(sock);
            vTaskDelay(2000 / portTICK_PERIOD_MS);
            continue;
        }
        ESP_LOGI("TCP Client", "Conexión establecida con el servidor");

        // Enviar datos de temperatura y humedad
        while (1) {
            // Simular obtención de temperatura y humedad, reemplaza estas líneas con los datos reales
            float temperatura = 25.5; // Por ejemplo, reemplaza por la variable real que mide temperatura
            float humedad = 57.0;     // Reemplaza por la variable que mide humedad

            char payload[128];
            snprintf(payload, sizeof(payload), "Temperatura: %.2f °C, Humedad: %.2f %%", temperatura, humedad);
            
            int err = send(sock, payload, strlen(payload), 0);
            if (err < 0) {
                ESP_LOGE("TCP Client", "Error al enviar: errno %d", errno);
                break;
            }

            ESP_LOGI("TCP Client", "Datos enviados: %s", payload);

            // Recibir respuesta del servidor
            int len = recv(sock, rx_buffer, sizeof(rx_buffer) - 1, 0);
            if (len < 0) {
                ESP_LOGE("TCP Client", "Error al recibir: errno %d", errno);
                break;
            } else if (len == 0) {
                ESP_LOGI("TCP Client", "Conexión cerrada");
                break;
            } else {
                rx_buffer[len] = 0;
                ESP_LOGI("TCP Client", "Respuesta del servidor: %s", rx_buffer);
            }

            vTaskDelay(2000 / portTICK_PERIOD_MS); // Esperar 2 segundos antes del siguiente envío
        }

        if (sock != -1) {
            ESP_LOGI("TCP Client", "Cerrando socket y reiniciando conexión...");
            close(sock);
        }
    }
}

void app_main(void) {
    ESP_ERROR_CHECK(nvs_flash_init());
    wifi_init_sta(); // Inicializar WiFi

    xTaskCreate(tcp_client_task, "tcp_client", 4096, NULL, 5, NULL);
}
