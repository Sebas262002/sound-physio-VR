using UnityEngine;
using UnityEngine.Events;

public class SentarseTrigger : MonoBehaviour
{
    [Header("Config")]
    [SerializeField] private string tagXROrigin = "MainCamera"; // detecta la cámara VR
    [SerializeField] private float tiempoParaConfirmar = 2f;    // segundos que debe estar sentado

    [Header("Reorientación")]
    [SerializeField] private Transform xrOrigin;         // arrastra tu XR Origin (VR)
    [SerializeField] private Transform direccionDeseada;  // Empty apuntando hacia donde debe quedar mirando

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
                ReorientarUsuario();
                onUsuarioSentado?.Invoke();
                Debug.Log("[Silla] Usuario sentado confirmado - iniciando sesión");
            }
        }
    }

    private void ReorientarUsuario()
    {
        if (xrOrigin == null || direccionDeseada == null) return;

        float anguloActualCamara = Camera.main.transform.eulerAngles.y;
        float anguloDeseado = direccionDeseada.eulerAngles.y;
        float diferencia = anguloDeseado - anguloActualCamara;

        xrOrigin.RotateAround(Camera.main.transform.position, Vector3.up, diferencia);
    }
}