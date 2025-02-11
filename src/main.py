from typing import TypedDict
from PIL import Image
import aiohttp
import io
import chainlit as cl
from datasets import load_dataset
from google import genai
from google.genai.types import Tool, GenerateContentConfig, GoogleSearch, PartUnionDict
from google.genai.chats import AsyncChat

client = genai.Client()
model_id = "gemini-2.0-flash-001"

# for user
side_bar_prompt = """Here's the art piece we are discussing today:

- **Author**: {author_name}
- **Description**: {description}

Here is the image of the art piece. You can click on it to enlarge it."""

# for llm
init_conversation_prompt = """Here's the art piece we are discussing today:

- **Author**: {author_name}
- **Description**: {description}
- **Image url**: {image_url}

Here is the image of the art piece."""

system_prompt = """You are a highly knowledgable and extravert art director.
Your job is to entertain the user by highlighting interesting aspects
of the selected art piece and provoke an engaging conversation.
You can show images to the user using html, e.g. <img src=url />.
The images are hosted on https://iiif.micr.io/ which allows you to scale, crop and zoom the image.
For example `https://iiif.micr.io/<ID>/full/512,/0/default.jpg` will downsize the image to 512 pixels.
Use 512 pixels as the default, unless the user asks for a higher resolution.
You can also crop a specific part of the image as follows: "https://iiif.micr.io/<ID>/x,y,w,h/512,/0/default.jpg",
Here, the region of the full image to be returned is specified in terms of absolute pixel values.
The value of x represents the number of pixels from the 0 position on the horizontal axis.
The value of y represents the number of pixels from the 0 position on the vertical axis.
Thus the x,y position 0,0 is the upper left-most pixel of the image.
w represents the width of the region and h represents the height of the region in pixels.
Or use `pct:x,y,w,h` to provide percentages.
"""

google_search_tool = Tool(google_search=GoogleSearch())

ds = iter(
    load_dataset("vincentmin/rijksmuseum-oai", streaming=True, split="train")
    .shuffle()
    .filter(lambda record: not any(v is None for v in record.values()))
)


class Record(TypedDict):
    original_id: str
    image_url: str
    description: str
    artist_uri: str
    author_name: str


async def _load_image(url: str) -> Image.Image:
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            image_bytes = await response.read()
            image = Image.open(io.BytesIO(image_bytes))
            return image


async def load_image(url: str) -> Image.Image:
    """Load an image in 512px resolution keeping the aspect ratio"""
    return await _load_image(
        url.replace("/full/max/0/default.jpg", "/full/512,/0/default.jpg")
    )


async def llm(
    text: PartUnionDict | list[PartUnionDict],
    system_instruction: str | None = None,
):
    # Fetch chat session for current user
    chat: AsyncChat = cl.user_session.get("chat")
    system_instruction = system_instruction or system_prompt
    response = await chat.send_message(
        message=text,
        config=GenerateContentConfig(
            tools=[google_search_tool],
            response_modalities=["TEXT"],
            system_instruction=system_instruction,
        ),
    )
    # Display grounding context as elements.
    try:
        elements = [
            cl.Text(
                name="sources",
                content=response.candidates[
                    0
                ].grounding_metadata.search_entry_point.rendered_content,
                display="inline",
            )
        ]
    except Exception:
        elements = []
    print(response.text)
    return response, elements


async def display_sidebar(record: Record):
    text = side_bar_prompt.format(
        author_name=record["author_name"], description=record["description"]
    )
    elements = [
        cl.Text(content=text, name="art piece", display="side"),
        cl.Image(url=record["image_url"], name="image", display="side"),
    ]
    await cl.ElementSidebar.set_elements(elements)
    await cl.ElementSidebar.set_title("Art Piece")


async def initiate_conversation(record: Record):
    text = init_conversation_prompt.format(
        author_name=record["author_name"],
        description=record["description"],
        image_url=record["image_url"],
    )
    image = await load_image(record["image_url"])
    response, elements = await llm([text, image])
    await cl.Message(content=response.text, elements=elements).send()


@cl.on_chat_start
async def on_chat_start():
    # instantiate chat session to keep track of conversation
    chat = client.aio.chats.create(model=model_id)
    cl.user_session.set("chat", chat)

    # fetch random record for user
    record: Record = next(ds)
    print(record)

    await display_sidebar(record)
    await initiate_conversation(record)


@cl.on_message
async def main(message: cl.Message):
    response, elements = await llm(message.content)
    await cl.Message(content=response.text, elements=elements).send()
