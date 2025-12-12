"""
Evaluation Script for Speech Translation Models.

Runs trained models on test set and computes metrics.

Usage:
    python run_evaluation.py --model_dir outputs/whisper --output results/
    python run_evaluation.py --model_dir outputs/e2e --model_type e2e --output results/
"""

import argparse
import json
import time
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional

import torch
import pandas as pd
from tqdm import tqdm
from transformers import (
    WhisperForConditionalGeneration,
    WhisperProcessor,
    SpeechEncoderDecoderModel,
    Wav2Vec2Processor,
    MBart50Tokenizer
)

sys.path.insert(0, str(Path(__file__).parent.parent))

from data import VietEngDataset
from utils import MetricsComputer, setup_logger


logger = setup_logger("evaluate", log_to_file=False)


def load_whisper_model(model_dir: str):
    """Load trained Whisper model."""
    logger.info(f"Loading Whisper model from {model_dir}")
    model = WhisperForConditionalGeneration.from_pretrained(model_dir)
    processor = WhisperProcessor.from_pretrained(model_dir)
    
    if torch.cuda.is_available():
        model = model.cuda()
    
    model.eval()
    return model, processor


def load_e2e_model(model_dir: str):
    """Load trained E2E model."""
    logger.info(f"Loading E2E model from {model_dir}")
    model = SpeechEncoderDecoderModel.from_pretrained(model_dir)
    processor = Wav2Vec2Processor.from_pretrained(model_dir)
    tokenizer = MBart50Tokenizer.from_pretrained(model_dir)
    
    if torch.cuda.is_available():
        model = model.cuda()
    
    model.eval()
    return model, processor, tokenizer


def generate_whisper_predictions(
    model,
    processor,
    dataset: VietEngDataset,
    task: str = "transcribe"
) -> tuple:
    """
    Generate predictions with Whisper model.
    
    Args:
        model: Whisper model
        processor: Whisper processor
        dataset: Test dataset
        task: "transcribe" or "translate"
    
    Returns:
        Tuple of (predictions, references, latencies)
    """
    predictions = []
    references = []
    latencies = []
    
    device = next(model.parameters()).device
    
    forced_decoder_ids = processor.get_decoder_prompt_ids(
        language="vi",
        task=task
    )
    
    for i in tqdm(range(len(dataset)), desc=f"Whisper {task}"):
        sample = dataset[i]
        
        # Process audio
        inputs = processor(
            sample['audio'].numpy(),
            sampling_rate=16000,
            return_tensors="pt"
        ).input_features.to(device)
        
        # Generate
        start_time = time.perf_counter()
        with torch.no_grad():
            generated_ids = model.generate(
                inputs,
                forced_decoder_ids=forced_decoder_ids,
                max_length=256
            )
        latency = time.perf_counter() - start_time
        
        # Decode
        pred_text = processor.batch_decode(generated_ids, skip_special_tokens=True)[0]
        
        predictions.append(pred_text)
        references.append(sample['transcript'] if task == 'transcribe' else sample['translation'])
        latencies.append(latency)
    
    return predictions, references, latencies


def generate_e2e_predictions(
    model,
    processor,
    tokenizer,
    dataset: VietEngDataset,
    task: str = "transcribe"
) -> tuple:
    """
    Generate predictions with E2E model.
    
    Args:
        model: E2E model
        processor: Audio processor
        tokenizer: Text tokenizer
        dataset: Test dataset
        task: "transcribe" or "translate"
    
    Returns:
        Tuple of (predictions, references, latencies)
    """
    predictions = []
    references = []
    latencies = []
    
    device = next(model.parameters()).device
    
    # Task token
    task_token = "<2transcribe>" if task == "transcribe" else "<2translate>"
    
    for i in tqdm(range(len(dataset)), desc=f"E2E {task}"):
        sample = dataset[i]
        
        # Process audio
        inputs = processor(
            sample['audio'].numpy(),
            sampling_rate=16000,
            return_tensors="pt",
            padding=True
        )
        input_values = inputs.input_values.to(device)
        
        # Generate
        start_time = time.perf_counter()
        with torch.no_grad():
            generated_ids = model.generate(
                input_values,
                max_length=256,
                num_beams=4
            )
        latency = time.perf_counter() - start_time
        
        # Decode
        pred_text = tokenizer.batch_decode(generated_ids, skip_special_tokens=True)[0]
        
        # Remove task token if present
        pred_text = pred_text.replace(task_token, '').strip()
        
        predictions.append(pred_text)
        references.append(sample['transcript'] if task == 'transcribe' else sample['translation'])
        latencies.append(latency)
    
    return predictions, references, latencies


def evaluate_model(
    model_type: str,
    model_dir: str,
    test_csv: str,
    audio_root: str = "."
) -> Dict[str, Any]:
    """
    Evaluate a trained model.
    
    Args:
        model_type: "whisper" or "e2e"
        model_dir: Path to model checkpoint
        test_csv: Path to test CSV
        audio_root: Root directory for audio
    
    Returns:
        Dictionary with metrics and predictions
    """
    # Load model
    if model_type == "whisper":
        model, processor = load_whisper_model(model_dir)
        tokenizer = processor.tokenizer
    else:
        model, processor, tokenizer = load_e2e_model(model_dir)
    
    # Load dataset
    dataset = VietEngDataset(
        csv_path=test_csv,
        audio_root=audio_root
    )
    logger.info(f"Loaded {len(dataset)} test samples")
    
    # Generate predictions for both tasks
    if model_type == "whisper":
        asr_preds, asr_refs, asr_latencies = generate_whisper_predictions(
            model, processor, dataset, task="transcribe"
        )
        st_preds, st_refs, st_latencies = generate_whisper_predictions(
            model, processor, dataset, task="translate"
        )
    else:
        asr_preds, asr_refs, asr_latencies = generate_e2e_predictions(
            model, processor, tokenizer, dataset, task="transcribe"
        )
        st_preds, st_refs, st_latencies = generate_e2e_predictions(
            model, processor, tokenizer, dataset, task="translate"
        )
    
    # Compute metrics
    metrics_computer = MetricsComputer()
    metrics = metrics_computer.compute_all(
        asr_predictions=asr_preds,
        asr_references=asr_refs,
        st_predictions=st_preds,
        st_references=st_refs
    )
    
    # Add latency stats
    avg_latency = (sum(asr_latencies) + sum(st_latencies)) / (2 * len(dataset))
    metrics['avg_latency_ms'] = avg_latency * 1000
    
    logger.info("Evaluation Results:")
    for key, value in metrics.items():
        logger.info(f"  {key}: {value:.4f}")
    
    return {
        'model_type': model_type,
        'model_dir': model_dir,
        'metrics': metrics,
        'predictions': {
            'asr': list(zip(asr_preds, asr_refs)),
            'st': list(zip(st_preds, st_refs))
        }
    }


def save_results(results: Dict, output_dir: str, model_name: str) -> None:
    """Save evaluation results."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Save metrics
    metrics_file = output_dir / f"{model_name}_metrics.json"
    with open(metrics_file, 'w') as f:
        json.dump(results['metrics'], f, indent=2)
    logger.info(f"Saved metrics to {metrics_file}")
    
    # Save predictions
    predictions_file = output_dir / f"{model_name}_predictions.csv"
    
    rows = []
    for i, (asr_pred, asr_ref) in enumerate(results['predictions']['asr']):
        st_pred, st_ref = results['predictions']['st'][i]
        rows.append({
            'id': i,
            'asr_prediction': asr_pred,
            'asr_reference': asr_ref,
            'st_prediction': st_pred,
            'st_reference': st_ref
        })
    
    df = pd.DataFrame(rows)
    df.to_csv(predictions_file, index=False)
    logger.info(f"Saved predictions to {predictions_file}")


def main():
    parser = argparse.ArgumentParser(description='Evaluate Speech Translation Model')
    parser.add_argument(
        '--model_dir',
        type=str,
        required=True,
        help='Path to trained model directory'
    )
    parser.add_argument(
        '--model_type',
        type=str,
        choices=['whisper', 'e2e'],
        default='whisper',
        help='Model type'
    )
    parser.add_argument(
        '--test_csv',
        type=str,
        default='data/splits/test.csv',
        help='Path to test CSV'
    )
    parser.add_argument(
        '--audio_root',
        type=str,
        default='.',
        help='Root directory for audio files'
    )
    parser.add_argument(
        '--output',
        type=str,
        default='training/outputs/results',
        help='Output directory for results'
    )
    
    args = parser.parse_args()
    
    # Check GPU
    if torch.cuda.is_available():
        logger.info(f"GPU: {torch.cuda.get_device_name(0)}")
    else:
        logger.warning("No GPU detected")
    
    # Evaluate
    results = evaluate_model(
        model_type=args.model_type,
        model_dir=args.model_dir,
        test_csv=args.test_csv,
        audio_root=args.audio_root
    )
    
    # Save
    model_name = Path(args.model_dir).name
    save_results(results, args.output, model_name)
    
    print("\n" + "=" * 60)
    print("EVALUATION COMPLETE")
    print("=" * 60)
    for key, value in results['metrics'].items():
        print(f"  {key}: {value:.4f}")
    
    return 0


if __name__ == '__main__':
    exit(main())
