/**
 * Image Vision Extension
 *
 * Adds image understanding capabilities to agent input.
 * Processes image attachments from messages and includes them in container input.
 */

import type { AgentInputExtension } from '../types.js';
import { parseImageReferences } from './image.js';

export const imageVisionExtension: AgentInputExtension = {
  name: 'image-vision',
  version: '1.0.0',

  enhanceAgentInput: (context, draft) => {
    const imageAttachments = parseImageReferences(context.messages);
    if (imageAttachments.length > 0) {
      draft.containerInput.imageAttachments = imageAttachments;
    }
  },
};

// Re-export for use in other modules
export { parseImageReferences, processImage, isImageMessage } from './image.js';
export type { ProcessedImage, ImageAttachment } from './image.js';
