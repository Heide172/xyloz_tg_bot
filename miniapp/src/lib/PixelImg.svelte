<script lang="ts">
  import { onMount } from 'svelte';

  export let src: string;
  export let fallback = ''; // если src не загрузился (напр. спрайта ещё нет) — берём это
  export let px = 64; // целевое разрешение пикселизации
  export let alt = '';
  export let contain = false; // вписывать целиком (для фигур в полный рост), иначе cover

  let canvas: HTMLCanvasElement;

  function paint(ctx: CanvasRenderingContext2D, img: HTMLImageElement) {
    ctx.imageSmoothingEnabled = false;
    ctx.clearRect(0, 0, px, px);
    const r = contain
      ? Math.min(px / img.width, px / img.height)
      : Math.max(px / img.width, px / img.height);
    const w = img.width * r;
    const h = img.height * r;
    // по горизонтали — центр, по вертикали — «ноги» внизу (для фигур)
    const x = (px - w) / 2;
    const y = contain ? px - h : (px - h) / 2;
    ctx.drawImage(img, x, y, w, h);
  }

  function draw() {
    if (!canvas || !src) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const img = new Image();
    img.onload = () => paint(ctx, img);
    img.onerror = () => {
      const fb = fallback || '/farm/heroine_idle.png';
      if (src !== fb) {
        const img2 = new Image();
        img2.onload = () => paint(ctx, img2);
        img2.src = fb;
      }
    };
    img.src = src;
  }

  onMount(draw);
  $: if (canvas && src) draw();
</script>

<canvas bind:this={canvas} width={px} height={px} class="pixel-canvas" aria-label={alt}></canvas>

<style>
  .pixel-canvas {
    width: 100%;
    height: 100%;
    display: block;
    image-rendering: pixelated;
    image-rendering: crisp-edges;
    object-fit: cover;
  }
</style>
