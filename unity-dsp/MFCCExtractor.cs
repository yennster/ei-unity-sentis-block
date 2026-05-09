using System;
using UnityEngine;

namespace EI.VR
{
    /// <summary>
    /// Reimplementation of Edge Impulse's "Audio (MFCC)" DSP block — MFE
    /// followed by a DCT-II truncation to the requested number of cepstral
    /// coefficients. Used for speech / keyword spotting impulses.
    /// </summary>
    [Serializable]
    public class MFCCConfig
    {
        public int sampleRateHz = 16000;
        public float frameLengthSec = 0.02f;
        public float frameStrideSec = 0.01f;
        public int numFilters = 32;
        public int numCepstral = 13;
        public int fftSize = 256;
        public float lowFrequencyHz = 0f;
        public float highFrequencyHz = 0f;
        public float preEmphasis = 0.97f;
        public float floor = 1e-10f;
    }

    public static class MFCCExtractor
    {
        public static float[] Extract(float[] audio, MFCCConfig cfg)
        {
            // Reuse MFE for the log-mel-energy pipeline.
            var mfeCfg = new MFEConfig
            {
                sampleRateHz = cfg.sampleRateHz,
                frameLengthSec = cfg.frameLengthSec,
                frameStrideSec = cfg.frameStrideSec,
                numFilters = cfg.numFilters,
                fftSize = cfg.fftSize,
                lowFrequencyHz = cfg.lowFrequencyHz,
                highFrequencyHz = cfg.highFrequencyHz,
                preEmphasis = cfg.preEmphasis,
                floor = cfg.floor,
            };
            var logMel = MFEExtractor.Extract(audio, mfeCfg);
            int frameLen = Mathf.Max(1, Mathf.RoundToInt(cfg.sampleRateHz * cfg.frameLengthSec));
            int frameStride = Mathf.Max(1, Mathf.RoundToInt(cfg.sampleRateHz * cfg.frameStrideSec));
            int numFrames = audio.Length >= frameLen ? 1 + (audio.Length - frameLen) / frameStride : 0;

            // DCT-II per frame, keep first numCepstral coefficients.
            int N = cfg.numFilters;
            int K = Mathf.Min(cfg.numCepstral, N);
            var cosTable = BuildCosTable(N, K);
            var mfcc = new float[numFrames * K];
            for (int f = 0; f < numFrames; f++)
            {
                int frameOffset = f * N;
                int outOffset = f * K;
                for (int k = 0; k < K; k++)
                {
                    float sum = 0f;
                    for (int n = 0; n < N; n++) sum += logMel[frameOffset + n] * cosTable[k * N + n];
                    // Orthonormal DCT-II scaling (matches scipy/librosa default).
                    float scale = (k == 0) ? Mathf.Sqrt(1f / N) : Mathf.Sqrt(2f / N);
                    mfcc[outOffset + k] = sum * scale;
                }
            }
            return mfcc;
        }

        public static int FrameCount(int audioSamples, MFCCConfig cfg)
        {
            int frameLen = Mathf.Max(1, Mathf.RoundToInt(cfg.sampleRateHz * cfg.frameLengthSec));
            int frameStride = Mathf.Max(1, Mathf.RoundToInt(cfg.sampleRateHz * cfg.frameStrideSec));
            return audioSamples >= frameLen ? 1 + (audioSamples - frameLen) / frameStride : 0;
        }

        private static float[] BuildCosTable(int N, int K)
        {
            var cos = new float[K * N];
            for (int k = 0; k < K; k++)
            {
                for (int n = 0; n < N; n++)
                {
                    cos[k * N + n] = Mathf.Cos(Mathf.PI * (n + 0.5f) * k / N);
                }
            }
            return cos;
        }
    }
}
