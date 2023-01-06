from transformers import GPT2LMHeadModel, GPTNeoForCausalLM, GPT2Tokenizer

CONFIG = {
        'model_name': 'sberbank-ai/mGPT',
        'model_cls': GPT2LMHeadModel,
        # 'model_name': 'EleutherAI/gpt-neo-2.7B',
        # 'model_cls': GPTNeoForCausalLM,
        'min_length': 20,
        'max_length': 300,
        'num_beams': 1,
        'num_return_sequences': 1,
        'no_repeat_ngram_size': 2,
        'device': 'cuda'}
        
class Model:
    def __init__(self, config=CONFIG):
        gpt2_name = config['model_name']
        self.model = config['model_cls'].from_pretrained(gpt2_name)
        self.model.eval()
        self.tokenizer = GPT2Tokenizer.from_pretrained(gpt2_name)
        self.model.to(config['device'])
        self.config = config


    def generate(self, text):
        input_ids = self.tokenizer.encode(text, return_tensors='pt').to(self.config['device'])
        num_tokens = input_ids.shape[1]

        # set return_num_sequences > 1
        beam_outputs = self.model.generate(
            input_ids, 
            min_length=num_tokens + self.config['min_length'],
            max_length=num_tokens + self.config['max_length'], 
            num_beams=self.config['num_beams'], 
            no_repeat_ngram_size=self.config['no_repeat_ngram_size'], 
            num_return_sequences=self.config['num_return_sequences'], 
            early_stopping=True
        )

        return [self.tokenizer.decode(b, skip_special_tokens=True) for b in beam_outputs]
