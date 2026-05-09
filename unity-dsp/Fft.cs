using System;
using UnityEngine;

namespace EI.VR
{
    /// <summary>
    /// Iterative radix-2 Cooley-Tukey FFT for power-of-two real input.
    /// Output is the magnitude spectrum (length N/2 + 1) — phase is dropped
    /// since neither Spectral Analysis nor MFE/MFCC needs it.
    /// </summary>
    public static class Fft
    {
        /// <summary>Round n up to the next power of two.</summary>
        public static int NextPow2(int n)
        {
            int p = 1;
            while (p < n) p <<= 1;
            return p;
        }

        /// <summary>
        /// Magnitude spectrum of `input`. Length-N input is zero-padded to
        /// the next power of two. Returns magnitudes for bins 0..N/2.
        /// </summary>
        public static float[] Magnitude(float[] input, int? fftSize = null)
        {
            int n = fftSize ?? NextPow2(input.Length);
            if ((n & (n - 1)) != 0) throw new ArgumentException("fftSize must be power of two");
            var re = new float[n];
            var im = new float[n];
            int copyN = Mathf.Min(input.Length, n);
            Array.Copy(input, re, copyN);

            Run(re, im);

            int outLen = n / 2 + 1;
            var mag = new float[outLen];
            for (int i = 0; i < outLen; i++)
            {
                mag[i] = Mathf.Sqrt(re[i] * re[i] + im[i] * im[i]);
            }
            return mag;
        }

        /// <summary>In-place radix-2 FFT (re/im are full-length buffers).</summary>
        public static void Run(float[] re, float[] im)
        {
            int n = re.Length;
            if ((n & (n - 1)) != 0) throw new ArgumentException("Length must be power of two");

            // Bit-reversal permutation.
            int j = 0;
            for (int i = 0; i < n - 1; i++)
            {
                if (i < j)
                {
                    (re[i], re[j]) = (re[j], re[i]);
                    (im[i], im[j]) = (im[j], im[i]);
                }
                int k = n >> 1;
                while (k <= j) { j -= k; k >>= 1; }
                j += k;
            }

            // Cooley-Tukey butterflies.
            for (int size = 2; size <= n; size <<= 1)
            {
                int half = size >> 1;
                float theta = -2f * Mathf.PI / size;
                float wpr = Mathf.Cos(theta);
                float wpi = Mathf.Sin(theta);
                for (int i = 0; i < n; i += size)
                {
                    float wr = 1f, wi = 0f;
                    for (int k = 0; k < half; k++)
                    {
                        int a = i + k;
                        int b = a + half;
                        float tre = wr * re[b] - wi * im[b];
                        float tim = wr * im[b] + wi * re[b];
                        re[b] = re[a] - tre; im[b] = im[a] - tim;
                        re[a] += tre;        im[a] += tim;
                        float ntr = wr * wpr - wi * wpi;
                        wi = wr * wpi + wi * wpr;
                        wr = ntr;
                    }
                }
            }
        }
    }
}
