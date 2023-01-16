from transformers import GPT2LMHeadModel, GPTNeoForCausalLM, GPT2Tokenizer

CONFIG = {
        # 'model_name': 'sberbank-ai/mGPT',
        'model_name': "sberbank-ai/rugpt3large_based_on_gpt2",
        'model_cls': GPT2LMHeadModel,
        # 'model_name': 'EleutherAI/gpt-neo-2.7B',
        # 'model_cls': GPTNeoForCausalLM,
        'min_length': 20,
        'max_new_tokens': 200,
        'do_sample':True,
        'temperature': 0.4,
        'top_p': 0.9,
        'num_beams': 1,
        'num_return_sequences': 1,
        'no_repeat_ngram_size': 2,
        'device': 'cuda'}
        
class Model:
    def __init__(self, config=CONFIG):
        gpt2_name = config.pop('model_name')
        self.model = config.pop('model_cls').from_pretrained(gpt2_name)
        self.model.eval()
        self.tokenizer = GPT2Tokenizer.from_pretrained(gpt2_name)
        self.device = config.pop('device')
        self.model.to(self.device)
        self.config = config


    def generate(self, text):
        input_ids = self.tokenizer.encode(text, return_tensors='pt').to(self.device)

        out = self.model.generate(input_ids, **self.config)
        generated_text = list(map(self.tokenizer.decode, out))[0]

        return generated_text
