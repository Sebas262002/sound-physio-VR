using System.Collections;
using UnityEngine;
using UnityEngine.Events;
using TMPro;
using UnityEngine.UI;

public class PanelSeguridadAcomodo : MonoBehaviour
{
    [Header("Referencias UI")]
    [SerializeField] private CanvasGroup canvasGroupPanel;
    [SerializeField] private TextMeshProUGUI textoSeguridadUI;
    [SerializeField] private Image fondoNegro;

    [Header("Movimiento del texto (sube lento, tipo créditos)")]
    [SerializeField] private float desplazamientoInicialY = -150f;
    [SerializeField] private float desplazamientoFinalY = 400f;

    [Header("Tiempos (segundos) — debe coincidir con los 30s de estabilización en Python")]
    [SerializeField] private float duracionTotal = 30f;
    [SerializeField] private float duracionFadeIn = 2f;
    [SerializeField] private float duracionFadeOut = 1.5f;

    [TextArea]
    [SerializeField]
    private string textoSeguridad =
        "Por tu seguridad, no te pongas de pie durante la sesión. " +
        "Puedes mover la cabeza libremente para mirar alrededor, pero mantente sentado hasta que termine.";

    public UnityEvent onPanelFinalizado;

    private RectTransform textoRectTransform;
    private Vector2 posicionFinalTexto;

    private void Awake()
    {
        if (canvasGroupPanel != null)
        {
            canvasGroupPanel.alpha = 0f;
        }

        if (textoSeguridadUI != null)
        {
            textoRectTransform = textoSeguridadUI.rectTransform;
            posicionFinalTexto = textoRectTransform.anchoredPosition;
            textoRectTransform.anchoredPosition = posicionFinalTexto + new Vector2(0f, desplazamientoInicialY);
        }
    }

    public void MostrarPanelSeguridad()
    {
        if (textoSeguridadUI != null) textoSeguridadUI.text = textoSeguridad;
        StartCoroutine(SecuenciaPanel());
    }

    private IEnumerator SecuenciaPanel()
    {
        Vector2 posicionInicialTexto = posicionFinalTexto + new Vector2(0f, desplazamientoInicialY);
        Vector2 posicionFinalDesplazada = posicionFinalTexto + new Vector2(0f, desplazamientoFinalY);

        float duracionScroll = duracionTotal - duracionFadeOut;
        float t = 0f;

        while (t < duracionScroll)
        {
            t += Time.deltaTime;

            // El fondo se pone negro rápido, al inicio
            canvasGroupPanel.alpha = Mathf.Clamp01(t / duracionFadeIn);

            // El texto sube LENTO durante casi todo el tiempo del panel
            float progresoScroll = Mathf.Clamp01(t / duracionScroll);
            if (textoRectTransform != null)
                textoRectTransform.anchoredPosition = Vector2.Lerp(posicionInicialTexto, posicionFinalDesplazada, progresoScroll);

            yield return null;
        }
        canvasGroupPanel.alpha = 1f;

        float tOut = 0f;
        while (tOut < duracionFadeOut)
        {
            tOut += Time.deltaTime;
            canvasGroupPanel.alpha = Mathf.Lerp(1f, 0f, tOut / duracionFadeOut);
            yield return null;
        }
        canvasGroupPanel.alpha = 0f;

        if (textoRectTransform != null)
            textoRectTransform.anchoredPosition = posicionInicialTexto;

        onPanelFinalizado?.Invoke();
    }
}