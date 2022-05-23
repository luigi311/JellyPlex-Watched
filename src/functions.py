import os
from dotenv import load_dotenv
load_dotenv(override=True)

logfile = os.getenv("LOGFILE","log.log")

def logger(message, log_type=0):
    
    output = str(message)
    if log_type == 0:
        pass
    elif log_type == 1:
        output = f"[INFO]: {output}"
    elif log_type == 2:
        output = f"[ERROR]: {output}"
    else:
        output = None

    if output is not None:
        print(output)
        file = open(logfile, "a", encoding="utf-8")
        file.write(output + "\n")

# Reimplementation of distutils.util.strtobool due to it being deprecated
# Source: https://github.com/PostHog/posthog/blob/01e184c29d2c10c43166f1d40a334abbc3f99d8a/posthog/utils.py#L668
def str_to_bool(value: any) -> bool:
    if not value:
        return False
    return str(value).lower() in ("y", "yes", "t", "true", "on", "1")

# Get mapped value
def search_mapping(dictionary: dict, key_value: str):
    if key_value in dictionary.keys():
        return dictionary[key_value]
    elif key_value in dictionary.values():
        return list(dictionary.keys())[list(dictionary.values()).index(key_value)]
    else:
        return None
