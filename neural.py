import re
import json
import torch
from transformers import GPT2LMHeadModel, GPT2Tokenizer      


class Model:
    def __init__(self, config_path='config/model.json'):
        with open(config_path, 'r') as f:
            config = json.load(f)
        gpt2_name = config.pop('model_name')
        self.template = config.pop('template')

        self.device = config.pop('device')
        self.config = config
        self.context = ''

        self.get_model(gpt2_name, config.pop("model_cpt"))

    def answer(self, text):
        if text[-1] not in {'.', '?', '!'}:
            text += '.'

        self.context += self.template.format(text)
        response = self.generate(self.context)
        
        answer = self.process_response(response)
        self.context += answer

        return answer
    
    def process_response(self, response):
        split = re.split('(\.|\?|\!)', response)
        if '\n' in split[0]:
            answer = split[0].split('\n')[0] +  '.'
        else:
            answer = split[0]
            if len(split) > 1:
                answer += split[1]
        
        return answer

    def generate(self, text):
        max_input_size = self.model.config.n_positions
        if 'max_length' in self.config['generate_config']:
            max_input_size -= self.config['generate_config']['max_length']
        input_ids = self.tokenizer.encode(text, return_tensors='pt').to(self.device)
        if len(input_ids) > max_input_size:
            input_ids = input_ids[-max_input_size:]
        
        with torch.no_grad():
            out = self.model.generate(input_ids, **self.config['generate_config'])
        
        out = out[:, input_ids.shape[1]:]
        generated_text = list(map(self.tokenizer.decode, out))[0]
        
        return generated_text
    
    def get_model(self, model_name, cpt_path):
        self.tokenizer = GPT2Tokenizer.from_pretrained(model_name)
        self.model = GPT2LMHeadModel.from_pretrained(model_name)
        self.model.eval()
        
        if cpt_path is not None:
            cpt = torch.load(cpt_path, map_location='cpu')
            self.model.load_state_dict(cpt['model_state_dict'])

        self.model.to(self.device)

    def show_history(self):
        return self.context
    
    def clear_context(self):
        self.context = ''