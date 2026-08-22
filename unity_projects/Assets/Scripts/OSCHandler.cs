using UnityEngine;
using extOSC;

public class OSCHandler : MonoBehaviour
{
    [SerializeField] OSCReceiver receiver;
    [SerializeField] bool mostrarLogs = true;

    private OSCTransmitter transmitter;

    void Start()
    {
        if (receiver == null)
        {
            receiver = GetComponent<OSCReceiver>();
        }

        // Buscar transmitter para responder pings
        transmitter = GetComponent<OSCTransmitter>();
        if (transmitter == null)
        {
            Debug.LogWarning("[OSC] No hay OSCTransmitter en este GameObject - no se podrá responder ping");
        }

        if (receiver == null)
        {
            Debug.LogError("[OSC] No hay OSCReceiver asignado!");
            return;
        }

        receiver.Bind("/ambiente", OnAmbiente);
        receiver.Bind("/sesion/iniciar", OnIniciar);
        receiver.Bind("/sesion/terminar", OnTerminar);
        receiver.Bind("/ping", OnPing);

        Log($"Handlers registrados en puerto {receiver.LocalPort}");
    }

    void OnAmbiente(OSCMessage message)
    {
        if (message.Values.Count == 0) return;

        string nombre = message.Values[0].StringValue;
        Log($"Ambiente recibido: {nombre}");

        Material sky = Resources.Load<Material>($"Skyboxes/{nombre}");
        if (sky != null)
        {
            RenderSettings.skybox = sky;
            DynamicGI.UpdateEnvironment();
            Log($"Skybox aplicado: {nombre}");
        }
        else
        {
            Debug.LogWarning($"[OSC] Skybox no encontrado: Resources/Skyboxes/{nombre}");
        }
    }

    void OnIniciar(OSCMessage message)
    {
        string id = message.Values.Count > 0 ? message.Values[0].StringValue : "?";
        Log($"Sesion iniciada: {id}");
    }

    void OnTerminar(OSCMessage message)
    {
        Log("Sesion terminada");
    }

    void OnPing(OSCMessage message)
    {
        Log("Ping recibido desde Python");

        // Responder /pong al puerto que Python indicó
        if (message.Values.Count > 0 && transmitter != null)
        {
            int puertoRespuesta = message.Values[0].IntValue;

            // Configurar transmitter temporalmente al puerto que pide Python
            transmitter.RemoteHost = "127.0.0.1";
            transmitter.RemotePort = puertoRespuesta;

            var respuesta = new OSCMessage("/pong");
            transmitter.Send(respuesta);

            Log($"Pong enviado a puerto {puertoRespuesta}");
        }
    }

    void Log(string msg)
    {
        if (mostrarLogs) Debug.Log($"[OSC] {msg}");
    }
}