## Lectures

### Intro

- mentoin modern multimodal LLMs?

- add warfare use cases?

- challenges: add dog vs tiger exmaple (from legacy)

### Images as Data

- Figure 1: "image represented as a tensor" is missing

- Figure 2: "image shown as RGB and grayscale" is missing

- think about mentioning other encodings, such as huv

- add a "think about it" block after Figure 2, to ask if other numbers of channels are possible.

- then add more examples

- Figure 3: "same image shown as .." is missing
  -> show a camera trap image with a large and small animal
  -> also shown a second row with aspect-preserv resize and padding,etc

- section 3.2 dataset splits -> reg grouped splits
  -> add a figure showing a sequence of images form a trigger event

- section 3.3 data leakage -> show example with dog (is it in practical?)

- Figure inm 3.4 class imbalance is missing: add from camera trap example.

- Figure in 3.5 label quality: add example from camera trap with closeup shots.

- section 3.5 verify / cite reference for claim "models trained on noisy labels tend to first learn the clean patterns then gradually memorize..."

- section 3.6 add cow example image

### CNN

- 1.2 Invariance

-> Figure 6, change sub-figure headers, also consider 2x2 layout for better visibility

-> Figure 7, consider 2x2 layout and only show detection results.

- 2.1 convolution operation

-> create new animations / figures to describe and visualize how convolutions work (replace step-by-step figures by johnson)

- add this:

::: {.callout-tip}

## Train a CNN for image classification in your browser!

[CNN Explainer](https://poloclub.github.io/cnn-explainer/)
:::

### classificatoin

- 1. The classification Task

  -> distinguish between multi-label and multi-task classification

### Practical

- some concepts not yet introduced: e.g. DINO etc.
- some things might be out-dated, such as input-independent baselines
- consider illustrative training-progress ona fixed samples of images

-> check for overlapp with "images as data". move some figures to that lecture

-> consider moving this lecture from the "lectures" section to provide as a standalone training guide. if so, leave the figures in (duplication less relevant) + add modern pre-trained backbones (fine-tuning options)

### Visual Representations

- 3.2.Weakly Sueprvised

-> make sure the whole CLIP Loss callout box is an optional learning goal

- 3.3 Self-Supervised learning

-> make sure the callout boxes with the losses are marked as optional learning goals / or additional information

- 3.3.3 Self-Distillation

-> ideally: visualize the different dinov3 losses to make them more intuitive: Global Dino, Local iBOT, KoLeo, Gram anchoring

### Adaptation

- consider adding visual

### Vision Transformers

- check

## Demos

### Interactive Augmentation Invariance

1. Select an Image
2. Given a set of interactie augmentations: such as rotation, color etc.
3. Observer real-time classification results from a pre-trained model (maybe pre-compute)
4. serve / add to a notebook
