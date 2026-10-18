"""Conservative conversation-ending cues for the local call simulator."""
import re


def normalized(text: str) -> str:
    return ' '.join(re.sub(r"[^\w\s']", ' ', text.lower()).split())


def user_requested_hangup(text: str, previous_reply: str = '') -> bool:
    value = normalized(text)
    # Match complete requests, so "don't end the call" and descriptions of a
    # previous call cannot accidentally disconnect the caller.
    if re.fullmatch(
        r"(?:(?:yes|yeah|okay|ok|alright) )?"
        r"(?:(?:please|can you|could you|would you) )?"
        r"(?:(?:end|cut) (?:the |this |our )?call|"
        r"hang up(?: (?:the |this |our )?call)?|disconnect (?:the call|me))"
        r"(?: please| now| thank you| thanks)*", value
    ):
        return True
    if value in {'bye', 'bye bye', 'goodbye', 'good bye', "that's all", 'that is all',
                 "that's all thank you", 'that is all thank you'}:
        return True
    # A refusal only closes a conversation after an offer of further help, not
    # after an ordinary clinical question such as "Do you have a fever?".
    return value in {'no thanks', 'no thank you', 'nothing else', 'no that is all', "no that's all"} and bool(
        re.search(r'anything else|any (?:other|more) (?:symptoms|questions)|'
                  r'would you like to (?:book|schedule)|can i help.*else', previous_reply.lower())
    )


def assistant_said_farewell(text: str) -> bool:
    # Used only on the completed assistant response, never on partial tokens.
    # A question means the assistant is still asking for input.
    return '?' not in text and bool(re.search(
        r'(?:^|\b)(?:goodbye|good bye|bye|have a (?:good|great|nice) (?:day|evening)|take care(?: of yourself)?)$',
        normalized(text)
    ))
