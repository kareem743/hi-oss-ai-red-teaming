"""Tiny local word-transition model for workflow testing, not clinical inference."""
import hashlib,random
DEMO_ID='brite-demo-local'
CORPUS=(
 'This is a fictional test response. The conversation is recorded for reviewer analysis.',
 'This example is for testing the chat interface. A reviewer can flag the response.',
 'The demo does not provide clinical guidance. Use fictional information for this test.',
 'The response is generated locally. No external model API is called.',
 'This synthetic example is not a medical assessment. Finish the conversation when ready.',
)
async def chunks(model,history,env):
    seed=hashlib.sha256((model.get('system_prompt','')+'\n'+history[-1]['content']).encode()).digest()
    rng=random.Random(seed)
    transitions={}
    for sentence in CORPUS:
        words=['<start>']+sentence.split()+['<end>']
        for a,b in zip(words,words[1:]):transitions.setdefault(a,[]).append(b)
    yield 'Synthetic demo response. '
    word='<start>';out=[]
    for _ in range(32):
        word=rng.choice(transitions.get(word,['<end>']))
        if word=='<end>':break
        out.append(word)
    yield ' '.join(out)
    yield ' [Local demo; no medical advice or paid API usage.]'
