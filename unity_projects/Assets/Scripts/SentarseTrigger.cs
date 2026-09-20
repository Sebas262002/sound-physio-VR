using UnityEngine;
using UnityEngine.Events;

public class SentarseTrigger : MonoBehaviour
{
    [Header("Config")]
    [SerializeField] private string tagXROrigin = "MainCamera"; // detecta la cámara VR
    [SerializeField] private float tiempoParaConfirmar = 2f;    // segundos que debe estar sentado

    [Header("Eventos")]
    public UnityEvent onUsuarioSentado;
    public UnityEvent onUsuarioSeLevanta;

    private bool usuarioDentro = false;
    private float tiempoDentro = 0f;
    private bool sesionYaIniciada = false;

    void OnTriggerEnter(Collider other)
    {
        if (other.CompareTag(tagXROrigin))
        {
            usuarioDentro = true;
            tiempoDentro = 0f;
            Debug.Log("[Silla] Usuario acercándose a la silla");
        }
    }

    void OnTriggerExit(Collider other)
    {
        if (other.CompareTag(tagXROrigin))
        {
            usuarioDentro = false;
            tiempoDentro = 0f;
            if (sesionYaIniciada)
            {
                sesionYaIniciada = false;
                onUsuarioSeLevanta?.Invoke();
                Debug.Log("[Silla] Usuario se levantó");
            }
        }
    }

    void Update()
    {
        if (usuarioDentro && !sesionYaIniciada)
        {
            tiempoDentro += Time.deltaTime;
            if (tiempoDentro >= tiempoParaConfirmar)
            {
                sesionYaIniciada = true;
                onUsuarioSentado?.Invoke();
                Debug.Log("[Silla] Usuario sentado confirmado - iniciando sesión");
            }
        }
    }
}