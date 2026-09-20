using UnityEngine;
using UnityEngine.Events;
using extOSC;

public class SesionStateMachine : MonoBehaviour
{
    public enum Estado { Idle, Caminando, Sentado, SesionActiva, SesionTerminada, Salida }

    [Header("Config")]
    [SerializeField] private float duracionSesionSegundos = 300f; // 5 minutos
    [SerializeField] private OSCTransmitter oscTransmitter;
    [SerializeField] private string hostPython = "127.0.0.1";
    [SerializeField] private int puertoPython = 9000;

    [Header("Eventos")]
    public UnityEvent onSesionInicia;
    public UnityEvent onSesionTermina;

    private Estado estadoActual = Estado.Idle;
    private float tiempoRestante = 0f;

    public Estado EstadoActual => estadoActual;
    public float TiempoRestante => tiempoRestante;

    void Start()
    {
        if (oscTransmitter != null)
        {
            oscTransmitter.RemoteHost = hostPython;
            oscTransmitter.RemotePort = puertoPython;
        }
        CambiarEstado(Estado.Idle);
    }

    public void UsuarioSeSento()
    {
        if (estadoActual == Estado.Idle || estadoActual == Estado.Caminando)
        {
            CambiarEstado(Estado.Sentado);
            Invoke(nameof(IniciarSesion), 3f); // 3s de preparación
        }
    }

    public void UsuarioSeLevanta()
    {
        if (estadoActual == Estado.SesionActiva)
        {
            TerminarSesion();
        }
    }

    void IniciarSesion()
    {
        CambiarEstado(Estado.SesionActiva);
        tiempoRestante = duracionSesionSegundos;
        EnviarOSC("/sesion/inicio");
        onSesionInicia?.Invoke();
        Debug.Log("[Sesion] INICIADA");
    }

    void TerminarSesion()
    {
        CambiarEstado(Estado.SesionTerminada);
        EnviarOSC("/sesion/fin");
        onSesionTermina?.Invoke();
        Debug.Log("[Sesion] TERMINADA");
    }

    void Update()
    {
        if (estadoActual == Estado.SesionActiva)
        {
            tiempoRestante -= Time.deltaTime;
            if (tiempoRestante <= 0f)
            {
                TerminarSesion();
            }
        }
    }

    void CambiarEstado(Estado nuevo)
    {
        estadoActual = nuevo;
        Debug.Log($"[Estado] → {nuevo}");
        EnviarOSC($"/sesion/estado", nuevo.ToString());
    }

    void EnviarOSC(string address, string valor = null)
    {
        if (oscTransmitter == null) return;
        var msg = new OSCMessage(address);
        if (valor != null) msg.AddValue(OSCValue.String(valor));
        oscTransmitter.Send(msg);
    }
}