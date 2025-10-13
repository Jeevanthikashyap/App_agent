import google.generativeai as genai # MODIFIED: Import Google's library
models = list(genai.list_models())
for model in models:
    print(model)