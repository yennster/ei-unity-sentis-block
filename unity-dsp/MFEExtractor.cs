using System;
using UnityEngine;

namespace EI.VR
{
    /// <summary>
    /// Reimplementation of Edge Impulse's "Audio (MFE)" DSP block — log
    /// mel-filterbank energies, the recommended block for sound classification.
    ///
    /// Output shape is (numFrames, numFilters), flattened in row-major
    /// (frame-major) order to match EI's tensor layout. Match the inspector
    /// parameters to your impulse's Audio MFE block — frame length / stride
    /// / filter count are the ones most often tweaked.
    /// </summary>
    [Serializable]
    public class MFEConfig
    {
        public int sampleRateHz = 16000;
        public float frameLengthSec = 0.02f;
        public float frameStrideSec = 0.01f;
        public int numFilters = 32;
        public int fftSize = 256;
        public float lowFrequencyHz = 0f;
        public float highFrequencyHz = 0f; // 0 = sampleRate/2
        public float preEmphasis = 0.97f;
        public float floor = 1e-10f;
    }

    public static class MFEExtractor
    {
        public static float[] Extract(float[] audio, MFEConfig cfg)
        {
            // 1. Pre-emphasis filter.
            var emphasized = new float[audio.Length];
            emphasized[0] = audio[0];
            for (int i = 1; i < audio.Length; i++)
            {
                emphasized[i] = audio[i] - cfg.preEmphasis * audio[i - 1];
            }

            int frameLen = Mathf.Max(1, Mathf.RoundToInt(cfg.sampleRateHz * cfg.frameLengthSec));
            int frameStride = Mathf.Max(1, Mathf.RoundToInt(cfg.sampleRateHz * cfg.frameStrideSec));
            int numFrames = audio.Length >= frameLen ? 1 + (audio.Length - frameLen) / frameStride : 0;
            int fft = cfg.fftSize >= frameLen ? cfg.fftSize : Fft.NextPow2(frameLen);
            float highHz = cfg.highFrequencyHz > 0f ? cfg.highFrequencyHz : cfg.sampleRateHz * 0.5f;
            int specBins = fft / 2 + 1;

            // 2. Mel filterbank precomputation.
            var melFilters = BuildMelFilterbank(cfg.numFilters, fft, cfg.sampleRateHz, cfg.lowFrequencyHz, highHz);

            // 3. Hann window.
            var window = new float[frameLen];
            for (int i = 0; i < frameLen; i++)
            {
                window[i] = 0.5f * (1f - Mathf.Cos(2f * Mathf.PI * i / (frameLen - 1)));
            }

            var output = new float[numFrames * cfg.numFilters];
            var frame = new float[fft];
            for (int f = 0; f < numFrames; f++)
            {
                int start = f * frameStride;
                Array.Clear(frame, 0, fft);
                for (int i = 0; i < frameLen; i++) frame[i] = emphasized[start + i] * window[i];
                var mag = Fft.Magnitude(frame, fft);

                // Power spectrum.
                var power = new float[specBins];
                for (int i = 0; i < specBins; i++) power[i] = mag[i] * mag[i] / fft;

                // Apply mel filterbank, take log.
                for (int m = 0; m < cfg.numFilters; m++)
                {
                    float energy = 0f;
                    var filter = melFilters[m];
                    for (int i = 0; i < specBins; i++) energy += power[i] * filter[i];
                    output[f * cfg.numFilters + m] = Mathf.Log(Mathf.Max(cfg.floor, energy));
                }
            }
            return output;
        }

        // Slaney-style triangular mel filterbank.
        private static float[][] BuildMelFilterbank(
            int numFilters, int fftSize, int sampleRate, float lowHz, float highHz)
        {
            var filters = new float[numFilters][];
            int specBins = fftSize / 2 + 1;
            float lowMel = HzToMel(lowHz);
            float highMel = HzToMel(highHz);
            // numFilters + 2 evenly-spaced points in mel space, including endpoints.
            var melPoints = new float[numFilters + 2];
            for (int i = 0; i < melPoints.Length; i++)
            {
                melPoints[i] = lowMel + (highMel - lowMel) * i / (numFilters + 1);
            }
            var binPoints = new int[melPoints.Length];
            for (int i = 0; i < melPoints.Length; i++)
            {
                binPoints[i] = Mathf.FloorToInt((fftSize + 1) * MelToHz(melPoints[i]) / sampleRate);
                if (binPoints[i] < 0) binPoints[i] = 0;
                if (binPoints[i] >= specBins) binPoints[i] = specBins - 1;
            }
            for (int m = 0; m < numFilters; m++)
            {
                int left = binPoints[m];
                int center = binPoints[m + 1];
                int right = binPoints[m + 2];
                var f = new float[specBins];
                for (int k = left; k < center; k++)
                {
                    if (center == left) continue;
                    f[k] = (k - left) / (float)(center - left);
                }
                for (int k = center; k <= right; k++)
                {
                    if (right == center) continue;
                    f[k] = (right - k) / (float)(right - center);
                }
                filters[m] = f;
            }
            return filters;
        }

        private static float HzToMel(float hz) => 2595f * Mathf.Log10(1f + hz / 700f);
        private static float MelToHz(float mel) => 700f * (Mathf.Pow(10f, mel / 2595f) - 1f);
    }
}
