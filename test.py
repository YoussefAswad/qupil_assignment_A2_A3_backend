import json
import textwrap

import google.generativeai as genai

# read the API key from file
with open("./google-ai-key.txt", "r") as f:
    api_key = f.read().strip()

genai.configure(api_key=api_key)
model = genai.GenerativeModel("gemini-pro")

# description = """I am available between noon and 4pm on weekends, after 7 pm to midnight on
# Monday and Wednesday, and after 9pm otherwise"""

description = """I am available between 7pm and 9pm on weekdays, and between 10am and 2pm on weekends"""

response = model.generate_content(
    textwrap.dedent(
        """\
    Please return JSON the a weekly schedule from this decription using the following schema:

    {"day_name": list[TIMESLOT]}

    TIMESLOT = {start_time": str, "end_time": str}

    All fields are required.

    Important: Only return a single piece of valid JSON text.
    Important: Friday and Saturday are the only weekend days.
    Important: Sunday is a weekday.
    Important: The start_time and end_time are in 24-hour format.

    Here is the description to use for the schedule:

    """
    )
    + description
)

json_text = response.text.strip("`\r\n ").removeprefix("json")

try:
    json_data = json.loads(json_text)
except json.JSONDecodeError:
    print("Invalid JSON response!")
    exit(1)

print(json.dumps(json_data, indent=4))
