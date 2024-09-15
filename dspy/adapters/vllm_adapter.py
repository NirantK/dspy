import re
from .base import Adapter
import base64
import requests
import io
import os
try:
    from PIL import Image
except ImportError:
    print("PIL is not installed, please install it to use image processing features.")

field_header_pattern = re.compile(r'\[\[\[\[ #### (\w+) #### \]\]\]\]')


class ImageChatAdapter(Adapter):
    def __init__(self):
        pass

    def format(self, signature, demos, inputs):
        messages = []
        messages.append({"role": "system", "content": prepare_instructions(signature)})

        for demo in demos:
            output_fields_, demo_ = list(signature.output_fields.keys()) + ['completed'], {**demo, 'completed': ''}
            messages.append({"role": "user", "content": format_chat_turn(signature.input_fields.keys(), demo)})
            messages.append({"role": "assistant", "content": format_chat_turn(output_fields_, demo_)})
        
        messages.append({"role": "user", "content": format_chat_turn(signature.input_fields.keys(), inputs)})
        return messages
    
    def parse(self, signature, completion):
        sections = [(None, [])]

        for line in completion.splitlines():
            match = field_header_pattern.match(line.strip())
            if match: sections.append((match.group(1), []))
            else: sections[-1][1].append(line)

        sections = [(k, '\n'.join(v).strip()) for k, v in sections]

        fields = {}
        for k, v in sections:
            if (k not in fields) and (k in signature.output_fields): fields[k] = v

        if fields.keys() != signature.output_fields.keys():
            raise ValueError(f"Expected {signature.output_fields.keys()} but got {fields.keys()}")

        return fields


def format_fields(fields):
    return '\n\n'.join([f"[[[[ #### {k} #### ]]]]\n{v}" for k, v in fields.items()]).strip()

def format_chat_turn(field_names, values):
    if not set(values).issuperset(set(field_names)):
        raise ValueError(f"Expected {field_names} but got {values.keys()}")
    
    text_content = format_fields({k: values[k] for k in field_names if 'image' not in k})
    
    request = []
    
    for k in field_names:
        if 'image' in k:
            image = values[k]
            if not image:
                continue
            image_base64 = encode_image(image)
            if image_base64:
                request.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{image_base64}"
                    }
                })
            else:
                raise ValueError(f"Failed to encode image for field {k}")

    request.append({
        "type": "text",
        "text": text_content
    })
    
    return request

def encode_image(image):
    if hasattr(Image, 'Image') and isinstance(image, Image.Image):
        # PIL Image (including PngImageFile, JpegImageFile, etc.)
        buffered = io.BytesIO()
        image.save(buffered, format="PNG")
        return base64.b64encode(buffered.getvalue()).decode('utf-8')
    elif isinstance(image, str):
        if os.path.isfile(image):
            # Local file path
            with open(image, "rb") as image_file:
                return base64.b64encode(image_file.read()).decode('utf-8')
        else:
            # Assume it's a URL
            return encode_image_base64_from_url(image)
    else:
        raise ValueError(f"Unsupported image type. Must be PIL Image, file path, or URL. Got {type(image)}")

def encode_image_base64_from_url(image_url: str) -> str:
    """Encode an image retrieved from a remote url to base64 format."""
    with requests.get(image_url) as response:
        response.raise_for_status()
        return base64.b64encode(response.content).decode('utf-8')

def enumerate_fields(fields):
    parts = []
    for idx, (k, v) in enumerate(fields.items()):
        parts.append(f"{idx+1}. `{k}`")
        parts[-1] += f" ({v.annotation.__name__})"
        parts[-1] += f": {v.json_schema_extra['desc']}" if v.json_schema_extra['desc'] != f'${{{k}}}' else ''

    return '\n'.join(parts).strip()

def prepare_instructions(signature):
    parts = []
    parts.append("Your input fields are:\n" + enumerate_fields(signature.input_fields))
    parts.append("Your output fields are:\n" + enumerate_fields(signature.output_fields))
    parts.append("All interactions will be structured in the following way, with the appropriate values filled in.")

    parts.append(format_fields({f : f"{{{f}}}" for f in signature.input_fields}))
    parts.append(format_fields({f : f"{{{f}}}" for f in signature.output_fields}))
    parts.append(format_fields({'completed' : ""}))

    parts.append("You will receive some input fields in each interaction. " +
                 "Respond only with the corresponding output fields, starting with the field " +
                 ", then ".join(f"`{f}`" for f in signature.output_fields) +
                 ", and then ending with the marker for `completed`.")
    
    objective = ('\n' + ' ' * 8).join([''] + signature.instructions.splitlines())
    parts.append(f"In adhering to this structure, your objective is: {objective}")

    return '\n\n'.join(parts).strip()