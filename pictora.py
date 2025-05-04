# from asyncio.windows_events import NULL
# from fastapi import FastAPI, UploadFile, File, Form, HTTPException
# import google.generativeai as genai
# from fastapi.responses import JSONResponse, StreamingResponse
# from PIL import Image
# import io
# import torch
# import numpy as np
# from fastapi.middleware.cors import CORSMiddleware
# from transformers import AutoModel, AutoTokenizer, AutoConfig, AutoModelForCausalLM
# from janus.models import MultiModalityCausalLM, VLChatProcessor

# app = FastAPI()

# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=["*"],
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )

# @app.post("/generate-pictora-response/")
# async def generate_response_pictora(api_key: str = Form(...), text_prompt: str = Form(...), image: UploadFile = File(None)):
#     genai.configure(api_key=api_key)
#     model = genai.GenerativeModel("gemini-1.5-flash")

#     image_bytes = await image.read()
#     pil_image = Image.open(io.BytesIO(image_bytes))

#     response = model.generate_content([text_prompt, pil_image])

#     return {"response": response.text}

# @app.post("/generate-clip-response/")
# async def generate_response_clip(api_key: str = Form(...), text_prompt: str = Form(...), image: UploadFile = File(None)):
#     genai.configure(api_key=api_key)
#     model = genai.GenerativeModel("gemini-2.0-flash")

#     image_bytes = await image.read()
#     pil_image = Image.open(io.BytesIO(image_bytes))

#     response = model.generate_content([text_prompt, pil_image])

#     return {"response": response.text}

# model_path = "deepseek-ai/Janus-Pro-1B"
# config = AutoConfig.from_pretrained(model_path)
# language_config = config.language_config
# language_config._attn_implementation = 'eager'
# vl_gpt = AutoModelForCausalLM.from_pretrained(model_path,
#                                               language_config=language_config,
#                                               trust_remote_code=True)
# # vl_gpt = vl_gpt.to(torch.bfloat16).cuda()
# vl_gpt = vl_gpt.to(torch.bfloat16)

# vl_chat_processor = VLChatProcessor.from_pretrained(model_path)
# tokenizer = vl_chat_processor.tokenizer
# cuda_device = 'cuda' if torch.cuda.is_available() else 'cpu'


# @torch.inference_mode()
# def multimodal_understanding(image_data, question, seed, top_p, temperature):
#     torch.cuda.empty_cache()
#     torch.manual_seed(seed)
#     np.random.seed(seed)
#     torch.cuda.manual_seed(seed)

#     conversation = [
#         {
#             "role": "User",
#             "content": f"<image_placeholder>\n{question}",
#             "images": [image_data],
#         },
#         {"role": "Assistant", "content": ""},
#     ]

#     pil_images = [Image.open(io.BytesIO(image_data)).convert("RGB")]
#     prepare_inputs = vl_chat_processor(
#         conversations=conversation, images=pil_images, force_batchify=True
#     ).to(cuda_device, dtype=torch.bfloat16)

#     inputs_embeds = vl_gpt.prepare_inputs_embeds(**prepare_inputs)
#     outputs = vl_gpt.language_model.generate(
#         inputs_embeds=inputs_embeds,
#         attention_mask=prepare_inputs.attention_mask,
#         pad_token_id=tokenizer.eos_token_id,
#         bos_token_id=tokenizer.bos_token_id,
#         eos_token_id=tokenizer.eos_token_id,
#         max_new_tokens=512,
#         do_sample=False if temperature == 0 else True,
#         use_cache=True,
#         temperature=temperature,
#         top_p=top_p,
#     )

#     answer = tokenizer.decode(outputs[0].cpu().tolist(), skip_special_tokens=True)
#     return answer


# @app.post("/generate-janus-response/")
# async def understand_image_and_question(
#     file: UploadFile = File(...),
#     question: str = Form(...),
#     seed: int = Form(42),
#     top_p: float = Form(0.95),
#     temperature: float = Form(0.1)
# ):
#     image_data = await file.read()
#     response = multimodal_understanding(image_data, question, seed, top_p, temperature)
#     return JSONResponse({"response": response})


# def generate(input_ids,
#              width,
#              height,
#              temperature: float = 1,
#              parallel_size: int = 5,
#              cfg_weight: float = 5,
#              image_token_num_per_image: int = 576,
#              patch_size: int = 16):
#     torch.cuda.empty_cache()
#     tokens = torch.zeros((parallel_size * 2, len(input_ids)), dtype=torch.int).to(cuda_device)
#     for i in range(parallel_size * 2):
#         tokens[i, :] = input_ids
#         if i % 2 != 0:
#             tokens[i, 1:-1] = vl_chat_processor.pad_id
#     inputs_embeds = vl_gpt.language_model.get_input_embeddings()(tokens)
#     generated_tokens = torch.zeros((parallel_size, image_token_num_per_image), dtype=torch.int).to(cuda_device)

#     pkv = None
#     for i in range(image_token_num_per_image):
#         outputs = vl_gpt.language_model.model(inputs_embeds=inputs_embeds, use_cache=True, past_key_values=pkv)
#         pkv = outputs.past_key_values
#         hidden_states = outputs.last_hidden_state
#         logits = vl_gpt.gen_head(hidden_states[:, -1, :])
#         logit_cond = logits[0::2, :]
#         logit_uncond = logits[1::2, :]
#         logits = logit_uncond + cfg_weight * (logit_cond - logit_uncond)
#         probs = torch.softmax(logits / temperature, dim=-1)
#         next_token = torch.multinomial(probs, num_samples=1)
#         generated_tokens[:, i] = next_token.squeeze(dim=-1)
#         next_token = torch.cat([next_token.unsqueeze(dim=1), next_token.unsqueeze(dim=1)], dim=1).view(-1)
#         img_embeds = vl_gpt.prepare_gen_img_embeds(next_token)
#         inputs_embeds = img_embeds.unsqueeze(dim=1)
#     patches = vl_gpt.gen_vision_model.decode_code(
#         generated_tokens.to(dtype=torch.int),
#         shape=[parallel_size, 8, width // patch_size, height // patch_size]
#     )

#     return generated_tokens.to(dtype=torch.int), patches


# def unpack(dec, width, height, parallel_size=5):
#     dec = dec.to(torch.float32).cpu().numpy().transpose(0, 2, 3, 1)
#     dec = np.clip((dec + 1) / 2 * 255, 0, 255)

#     visual_img = np.zeros((parallel_size, width, height, 3), dtype=np.uint8)
#     visual_img[:, :, :] = dec

#     return visual_img


# @torch.inference_mode()
# def generate_image(prompt, seed, guidance):
#     torch.cuda.empty_cache()
#     seed = seed if seed is not None else 12345
#     torch.manual_seed(seed)
#     torch.cuda.manual_seed(seed)
#     np.random.seed(seed)
#     width = 384
#     height = 384
#     parallel_size = 5

#     with torch.no_grad():
#         messages = [{'role': 'User', 'content': prompt}, {'role': 'Assistant', 'content': ''}]
#         text = vl_chat_processor.apply_sft_template_for_multi_turn_prompts(
#             conversations=messages,
#             sft_format=vl_chat_processor.sft_format,
#             system_prompt=''
#         )
#         text = text + vl_chat_processor.image_start_tag
#         input_ids = torch.LongTensor(tokenizer.encode(text))
#         _, patches = generate(input_ids, width // 16 * 16, height // 16 * 16, cfg_weight=guidance, parallel_size=parallel_size)
#         images = unpack(patches, width // 16 * 16, height // 16 * 16)

#         return [Image.fromarray(images[i]).resize((1024, 1024), Image.LANCZOS) for i in range(parallel_size)]


# @app.post("/generate_images/")
# async def generate_images(
#     prompt: str = Form(...),
#     seed: int = Form(None),
#     guidance: float = Form(5.0),
# ):
#     try:
#         images = generate_image(prompt, seed, guidance)
#         def image_stream():
#             for img in images:
#                 buf = io.BytesIO()
#                 img.save(buf, format='PNG')
#                 buf.seek(0)
#                 yield buf.read()

#         return StreamingResponse(image_stream(), media_type="multipart/related")
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=f"Image generation failed: {str(e)}")
#
from flask import Flask, request, jsonify
from pathlib import Path
from dotenv import load_dotenv
import io
from PIL import Image
import google.generativeai as PictoraAPI
from SEARCH import search_image
from flask_cors import CORS
from GOOGLE import search_google_image

load_dotenv()

app = Flask(__name__)
CORS(app)
# @app.route("/v1/pictora/respond-to-prompt", methods=["POST"])
# def generate_response_on_user_prompt():
#     try:
#         prompt = request.form.get("prompt")
#         mode = request.form.get("mode")
#         image = request.files.get("image")

#         if mode == "tti":
#             if not prompt:
#                 return jsonify({"error": "Prompt text is required"}), 400

#             image_path = search_image(prompt)

#             if not image_path:
#                 return jsonify({"error": "No matching image found"}), 404

#             if isinstance(image_path, str) and image_path.startswith("http"):
#                 return jsonify({"image_url": image_path})

#             image_url = f"/static/retrieved_images/{Path(image_path).name}"
#             return jsonify({"image_url": image_url})

#         elif mode == "itt":
#             # [NOTE] You should load this from environment securely
#             PictoraAPI.configure(api_key="AIzaSyAjJuSJjXpuCaWdU7HBsszxrmWjjZ8rHC4")
#             model = PictoraAPI.GenerativeModel("gemini-1.5-flash")

#             if image is None:
#                 return jsonify({"error": "No image uploaded"}), 400

#             image_bytes = image.read()
#             pil_image = Image.open(io.BytesIO(image_bytes))

#             response = model.generate_content([text_prompt, pil_image])
#             return jsonify({"response": response.text})

#         else:
#             return jsonify({"error": "Invalid mode"}), 400

#     except Exception as e:
#         return jsonify({"error": str(e)}), 500

@app.route("/v1/pictora/respond-to-prompt", methods=["POST"])
def generate_response_on_user_prompt():
    try:
        prompt = request.form.get("prompt")
        # mode = request.form.get("mode")
        image = request.files.get("image")

        # if mode == "tti":
        if not image:
        #     print('Prompt sent by the user: ', prompt)
        #     if not prompt:
        #         return jsonify({"error": "Prompt text is required"}), 400

        #     image_path = search_image(prompt)

        #     if not image_path:
        #         return jsonify({"error": "No matching image found"}), 404

        #     if isinstance(image_path, str) and image_path.startswith("http"):
        #         return jsonify({"image_url": image_path})

        #     image_url = f"/static/retrieved_images/{Path(image_path).name}"
        #     return jsonify({"image_url": image_url})
            if not prompt:
                return jsonify({"error": "No search term provided"}), 400

            image_url = search_google_image(prompt)

            if not image_url:
                return jsonify({"error": "No image found"}), 404

            return jsonify({"image_url": image_url})
        else:
            # [NOTE] You should load this from environment securely
            PictoraAPI.configure(api_key=os.getenv("PICTORA_API_KEY"))
            model = PictoraAPI.GenerativeModel(os.getenv("PICTORA_MODEL"))

            if image is None:
                return jsonify({"error": "No image uploaded"}), 400

            image_bytes = image.read()
            pil_image = Image.open(io.BytesIO(image_bytes))

            response = model.generate_content([prompt, pil_image])
            return jsonify({"response": response.text})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True)
