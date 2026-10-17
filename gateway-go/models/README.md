# Silero VAD v5 ONNX Model

To use Silero VAD with `yalue/onnxruntime_go`:

1. Download the Silero VAD v5 ONNX model:
   ```bash
   curl -L -o silero_vad.onnx https://github.com/snakers4/silero-vad/raw/master/src/silero_vad/data/silero_vad.onnx
   ```
2. When the model file `models/silero_vad.onnx` and `libonnxruntime` are present, `vad.NewSileroONNXDetector` will load the tensor model.
3. If ONNX runtime is absent, `EnergyVADDetector` automatically handles adaptive acoustic voice detection without crashing.
