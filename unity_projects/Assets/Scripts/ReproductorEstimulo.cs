using UnityEngine;

public class ReproductorEstimulo : MonoBehaviour
{
    [Header("Config")]
    [SerializeField] private AudioSource audioSource;
    [SerializeField] private AudioClip clipFrecuenciaTerapeutica;
    [SerializeField] private AudioClip clipMusicaPreferida;
    [SerializeField] private AudioClip clipSilencioControl;

    public enum TipoEstimulo { Frecuencia, Musica, Silencio }

    void Start()
    {
        if (audioSource == null) audioSource = GetComponent<AudioSource>();
        audioSource.spatialBlend = 0f; // 2D → llega igual a ambos oídos (binaural correcto)
        audioSource.loop = false;
    }

    public void Reproducir(TipoEstimulo tipo)
    {
        AudioClip clip = tipo switch
        {
            TipoEstimulo.Frecuencia => clipFrecuenciaTerapeutica,
            TipoEstimulo.Musica => clipMusicaPreferida,
            TipoEstimulo.Silencio => clipSilencioControl,
            _ => null
        };

        if (clip != null)
        {
            audioSource.clip = clip;
            audioSource.Play();
            Debug.Log($"[Audio] Reproduciendo: {tipo}");
        }
    }

    public void ReproducirFrecuencia() => Reproducir(TipoEstimulo.Frecuencia);
    public void ReproducirMusica() => Reproducir(TipoEstimulo.Musica);
    public void ReproducirSilencio() => Reproducir(TipoEstimulo.Silencio);

    public void Detener()
    {
        audioSource.Stop();
        Debug.Log("[Audio] Detenido");
    }
}