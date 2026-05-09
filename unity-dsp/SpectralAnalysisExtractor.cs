using System;
using System.Collections.Generic;
using UnityEngine;

namespace EI.VR
{
    /// <summary>
    /// Reimplementation of Edge Impulse's "Spectral Analysis" DSP block —
    /// the default block for motion / IMU classifiers.
    ///
    /// For each axis of the input window, we emit:
    ///   • RMS
    ///   • Skewness
    ///   • Kurtosis
    ///   • The top-K spectral peaks (frequency Hz, magnitude) pairs
    ///   • Total spectral power inside each user-defined band
    ///
    /// Match the inspector parameters to your impulse's Spectral Analysis
    /// block so the resulting feature vector lines up with what the model
    /// was trained on. This is a pragmatic implementation — it follows the
    /// same recipe as EI's reference but isn't bit-exact.
    /// </summary>
    [Serializable]
    public class SpectralAnalysisConfig
    {
        public int sampleRateHz = 62;
        public int peakCount = 3;
        public float lowFrequencyHz = 0f;
        public float highFrequencyHz = 0f; // 0 = Nyquist
        public float[] powerEdges = { 0.1f, 0.5f, 1.0f, 2.0f, 5.0f }; // band edges in Hz
        public bool removeMean = true;
    }

    public static class SpectralAnalysisExtractor
    {
        /// <summary>
        /// Extract per-axis features and concatenate them into a single
        /// flat feature vector — the same layout EI's Spectral Analysis
        /// block produces.
        /// </summary>
        /// <param name="window">Length-N values for one axis (samples).</param>
        public static List<float> ExtractAxis(float[] window, SpectralAnalysisConfig cfg)
        {
            var features = new List<float>(8 + cfg.peakCount * 2 + Mathf.Max(0, cfg.powerEdges.Length - 1));

            // 1. Time-domain stats: RMS, skewness, kurtosis (and mean for centering).
            float mean = 0f;
            for (int i = 0; i < window.Length; i++) mean += window[i];
            mean /= window.Length;

            float[] x = window;
            if (cfg.removeMean)
            {
                x = new float[window.Length];
                for (int i = 0; i < window.Length; i++) x[i] = window[i] - mean;
            }

            float sumSq = 0f, sumCube = 0f, sumQuad = 0f;
            for (int i = 0; i < x.Length; i++)
            {
                float v = x[i];
                sumSq += v * v;
                sumCube += v * v * v;
                sumQuad += v * v * v * v;
            }
            float n = x.Length;
            float variance = sumSq / n;
            float std = Mathf.Sqrt(variance);
            float rms = Mathf.Sqrt(sumSq / n);
            float skew = std > 1e-9f ? (sumCube / n) / (std * std * std) : 0f;
            float kurt = variance > 1e-9f ? (sumQuad / n) / (variance * variance) - 3f : 0f;

            features.Add(rms);
            features.Add(skew);
            features.Add(kurt);

            // 2. FFT magnitude spectrum.
            int fftSize = Fft.NextPow2(x.Length);
            float[] mag = Fft.Magnitude(x, fftSize);
            float binHz = cfg.sampleRateHz / (float)fftSize;
            float lo = cfg.lowFrequencyHz;
            float hi = cfg.highFrequencyHz > 0f ? cfg.highFrequencyHz : cfg.sampleRateHz * 0.5f;

            // 3. Top-K peaks within [lo, hi]. Local maxima, then sort by magnitude.
            var peaks = new List<(float freq, float mag)>();
            for (int i = 1; i < mag.Length - 1; i++)
            {
                float f = i * binHz;
                if (f < lo || f > hi) continue;
                if (mag[i] > mag[i - 1] && mag[i] > mag[i + 1])
                {
                    peaks.Add((f, mag[i]));
                }
            }
            peaks.Sort((a, b) => b.mag.CompareTo(a.mag));
            for (int k = 0; k < cfg.peakCount; k++)
            {
                if (k < peaks.Count)
                {
                    features.Add(peaks[k].freq);
                    features.Add(peaks[k].mag);
                }
                else
                {
                    features.Add(0f);
                    features.Add(0f);
                }
            }

            // 4. Spectral power in each band defined by powerEdges.
            if (cfg.powerEdges != null && cfg.powerEdges.Length >= 2)
            {
                for (int e = 0; e < cfg.powerEdges.Length - 1; e++)
                {
                    float bandLo = cfg.powerEdges[e];
                    float bandHi = cfg.powerEdges[e + 1];
                    int binStart = Mathf.Max(0, Mathf.FloorToInt(bandLo / binHz));
                    int binEnd = Mathf.Min(mag.Length - 1, Mathf.CeilToInt(bandHi / binHz));
                    float power = 0f;
                    for (int i = binStart; i <= binEnd; i++) power += mag[i] * mag[i];
                    features.Add(power);
                }
            }

            return features;
        }

        /// <summary>
        /// Multi-axis convenience wrapper. Pass a flat ring-buffer in
        /// chronological order with `axes` interleaved channels.
        /// </summary>
        public static float[] ExtractMultiAxis(float[] interleaved, int axes, SpectralAnalysisConfig cfg)
        {
            int samples = interleaved.Length / axes;
            var per = new float[samples];
            var output = new List<float>();
            for (int a = 0; a < axes; a++)
            {
                for (int i = 0; i < samples; i++) per[i] = interleaved[i * axes + a];
                output.AddRange(ExtractAxis(per, cfg));
            }
            return output.ToArray();
        }
    }
}
