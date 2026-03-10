import fs from 'fs';
import path from 'path';

const MAX_DIMENSION = 1024;
const IMAGE_REF_PATTERN = /\[Image: (attachments\/[^\]]+)\]/g;

export interface ProcessedImage {
  content: string;
  relativePath: string;
}

export interface ImageAttachment {
  relativePath: string;
  mediaType: string;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function isImageMessage(msg: any): boolean {
  return !!msg?.message?.imageMessage;
}

export async function processImage(
  buffer: Buffer,
  groupDir: string,
  caption: string,
): Promise<ProcessedImage | null> {
  if (!buffer || buffer.length === 0) return null;

  // Use dynamic import for sharp to avoid issues if not installed
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let sharp: any;
  try {
    // Use template string to bypass TypeScript module resolution
    const moduleName = 'sharp';
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const sharpModule = await import(moduleName) as any;
    sharp = sharpModule.default;
  } catch {
    // sharp not installed, save without processing
    const attachDir = path.join(groupDir, 'attachments');
    fs.mkdirSync(attachDir, { recursive: true });

    const filename = `img-${Date.now()}-${Math.random().toString(36).slice(2, 6)}.jpg`;
    const filePath = path.join(attachDir, filename);
    fs.writeFileSync(filePath, buffer);

    const relativePath = `attachments/${filename}`;
    const content = caption
      ? `[Image: ${relativePath}] ${caption}`
      : `[Image: ${relativePath}]`;

    return { content, relativePath };
  }

  const resized = await sharp(buffer)
    .resize(MAX_DIMENSION, MAX_DIMENSION, { fit: 'inside', withoutEnlargement: true })
    .jpeg({ quality: 85 })
    .toBuffer();

  const attachDir = path.join(groupDir, 'attachments');
  fs.mkdirSync(attachDir, { recursive: true });

  const filename = `img-${Date.now()}-${Math.random().toString(36).slice(2, 6)}.jpg`;
  const filePath = path.join(attachDir, filename);
  fs.writeFileSync(filePath, resized);

  const relativePath = `attachments/${filename}`;
  const content = caption
    ? `[Image: ${relativePath}] ${caption}`
    : `[Image: ${relativePath}]`;

  return { content, relativePath };
}

export function parseImageReferences(
  messages: Array<{ content: string }>,
): ImageAttachment[] {
  const refs: ImageAttachment[] = [];
  for (const msg of messages) {
    let match: RegExpExecArray | null;
    IMAGE_REF_PATTERN.lastIndex = 0;
    while ((match = IMAGE_REF_PATTERN.exec(msg.content)) !== null) {
      // Always JPEG — processImage() normalizes all images to .jpg
      refs.push({ relativePath: match[1], mediaType: 'image/jpeg' });
    }
  }
  return refs;
}
