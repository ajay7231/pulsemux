package audio

import (
	"encoding/binary"
	"math"
)

// muLawToLinearTable provides a pre-computed lookup table for instantaneous
// G.711 mu-law byte to signed 16-bit PCM integer decoding.
var muLawToLinearTable [256]int16

func init() {
	for i := 0; i < 256; i++ {
		muLawToLinearTable[i] = decodeMuLawByte(byte(i))
	}
}

// decodeMuLawByte computes ITU-T G.711 mu-law decoding algorithm.
func decodeMuLawByte(b byte) int16 {
	u := ^int(b)
	sign := u & 0x80
	exponent := (u >> 4) & 0x07
	mantissa := u & 0x0F
	sample := ((mantissa << 3) + 0x84) << exponent
	sample -= 0x84
	if sign == 0 {
		sample = -sample
	}
	if sample > 32767 {
		sample = 32767
	} else if sample < -32768 {
		sample = -32768
	}
	return int16(sample)
}

// linearToMuLawByte converts a signed 16-bit PCM sample to 8-bit mu-law.
func linearToMuLawByte(pcm int16) byte {
	const cClip = 32635
	const cBias = 0x84

	sample := int(pcm)
	sign := 0
	if sample < 0 {
		sign = 0x80
		sample = -sample
	}
	if sample > cClip {
		sample = cClip
	}
	sample += cBias

	exponent := 7
	for expMask := 0x4000; (sample&expMask) == 0 && exponent > 0; expMask >>= 1 {
		exponent--
	}
	mantissa := (sample >> (exponent + 3)) & 0x0F
	mu := byte(sign | (exponent << 4) | mantissa)
	return ^mu
}

// DecodeMuLaw8kToPCM16k converts 8kHz G.711 mu-law audio to 16kHz 16-bit mono Linear PCM
// via linear interpolation resampler. Input size N bytes yields 4*N bytes output.
// Operates strictly in memory with zero allocations per sample.
func DecodeMuLaw8kToPCM16k(muLaw []byte) []byte {
	if len(muLaw) == 0 {
		return nil
	}

	// 1 sample in mu-law (8kHz) -> 2 samples in 16kHz PCM (each 2 bytes = 4 bytes total)
	out := make([]byte, len(muLaw)*4)

	var prev int16
	for i, b := range muLaw {
		curr := muLawToLinearTable[b]

		var interp int16
		if i == 0 {
			interp = curr
		} else {
			// Linear midpoint interpolation
			interp = int16((int32(prev) + int32(curr)) / 2)
		}

		offset := i * 4
		// Sample 1 (interpolated)
		binary.LittleEndian.PutUint16(out[offset:], uint16(interp))
		// Sample 2 (original sample point)
		binary.LittleEndian.PutUint16(out[offset+2:], uint16(curr))

		prev = curr
	}

	return out
}

// EncodePCM16kToMuLaw8k downsamples 16kHz 16-bit mono Linear PCM to 8kHz mu-law for telephony.
// Takes every 2nd sample (decimation) and encodes to mu-law.
func EncodePCM16kToMuLaw8k(pcm []byte) []byte {
	numSamples := len(pcm) / 2
	if numSamples == 0 {
		return nil
	}

	// Decimate 2:1 (16kHz to 8kHz)
	out := make([]byte, numSamples/2)
	for i := 0; i < len(out); i++ {
		sampleIdx := i * 2 * 2 // 2 samples per step, 2 bytes per sample
		if sampleIdx+1 < len(pcm) {
			sample := int16(binary.LittleEndian.Uint16(pcm[sampleIdx : sampleIdx+2]))
			out[i] = linearToMuLawByte(sample)
		}
	}

	return out
}

// CalculateRMS computes Root-Mean-Square energy of a 16-bit PCM frame.
// Useful for fallback energy-based thresholding and silence validation.
func CalculateRMS(pcm []byte) float64 {
	numSamples := len(pcm) / 2
	if numSamples == 0 {
		return 0.0
	}

	var sumSq float64
	for i := 0; i < len(pcm)-1; i += 2 {
		sample := float64(int16(binary.LittleEndian.Uint16(pcm[i : i+2])))
		sumSq += sample * sample
	}

	return math.Sqrt(sumSq / float64(numSamples))
}
