
# coding: utf-8

# ## Boilerplate

# In[ ]:

from config import Config
import numpy as np
import pandas as pd
import time
import math
pd.set_option('display.max_rows', None)
ROOT_PATH = Config.ROOT_PATH
import torch
import torch.nn as nn
from torch.autograd import Variable
import torch.nn.functional as F


# ## Functions to accomplish attention
def batch_matmul_bias(seq, weight, bias, nonlinearity=''):
    s = None
    bias_dim = bias.size()
    for i in range(seq.size(0)):
        _s = torch.mm(seq[i], weight) 
        _s_bias = _s + bias.expand(bias_dim[0], _s.size()[0]).transpose(0,1)
        if(nonlinearity=='tanh'):
            _s_bias = torch.tanh(_s_bias)
        _s_bias = _s_bias.unsqueeze(0)
        if(s is None):
            s = _s_bias
        else:
            s = torch.cat((s,_s_bias),0)
    return s.squeeze()


# In[3]:


def batch_matmul(seq, weight, nonlinearity=''):
    s = None
    for i in range(seq.size(0)):
        _s = torch.mm(seq[i], weight)
        if(nonlinearity=='tanh'):
            _s = torch.tanh(_s)
        _s = _s.unsqueeze(0)
        if(s is None):
            s = _s
        else:
            s = torch.cat((s,_s),0)
    return s.squeeze()


# In[4]:


def attention_mul(rnn_outputs, att_weights):
    attn_vectors = None
    for i in range(rnn_outputs.size(0)):
        h_i = rnn_outputs[i]
        a_i = att_weights[i].unsqueeze(1).expand_as(h_i)
        h_i = a_i * h_i
        h_i = h_i.unsqueeze(0)
        if(attn_vectors is None):
            attn_vectors = h_i
        else:
            attn_vectors = torch.cat((attn_vectors,h_i),0)
    return torch.sum(attn_vectors, 0).unsqueeze(0)


# ## Word attention model with bias

# In[5]:


class AttentionWordRNN(nn.Module):
    
    
    def __init__(self, batch_size, num_tokens, embed_size, word_gru_hidden, bidirectional= True):        
        
        super(AttentionWordRNN, self).__init__()
        
        self.batch_size = batch_size
        self.num_tokens = num_tokens
        self.embed_size = embed_size
        self.word_gru_hidden = word_gru_hidden
        self.bidirectional = bidirectional
        
        self.lookup = nn.Embedding(num_tokens, embed_size)
        if bidirectional == True:
            self.word_gru = nn.GRU(embed_size, word_gru_hidden, bidirectional= True)
            self.weight_W_word = nn.Parameter(torch.Tensor(2* word_gru_hidden,2*word_gru_hidden))
            self.bias_word = nn.Parameter(torch.Tensor(2* word_gru_hidden,1))
            self.weight_proj_word = nn.Parameter(torch.Tensor(2*word_gru_hidden, 1))
        else:
            self.word_gru = nn.GRU(embed_size, word_gru_hidden, bidirectional= False)
            self.weight_W_word = nn.Parameter(torch.Tensor(word_gru_hidden, word_gru_hidden))
            self.bias_word = nn.Parameter(torch.Tensor(word_gru_hidden,1))
            self.weight_proj_word = nn.Parameter(torch.Tensor(word_gru_hidden, 1))
            
        self.softmax_word = nn.Softmax()
        self.weight_W_word.data.uniform_(-0.1, 0.1)
        self.weight_proj_word.data.uniform_(-0.1,0.1)

        
        
    def forward(self, embed, state_word):
        # embeddings
        embedded = self.lookup(embed)
        # word level gru
        output_word, state_word = self.word_gru(embedded, state_word)
#         print output_word.size()
        word_squish = batch_matmul_bias(output_word, self.weight_W_word,self.bias_word, nonlinearity='tanh')
        word_attn = batch_matmul(word_squish, self.weight_proj_word)
        word_attn_norm = self.softmax_word(word_attn.transpose(1,0))
        word_attn_vectors = attention_mul(output_word, word_attn_norm.transpose(1,0))        
        return word_attn_vectors, state_word, word_attn_norm
    
    def init_hidden(self):
        if self.bidirectional == True:
            return Variable(torch.zeros(2, self.batch_size, self.word_gru_hidden))
        else:
            return Variable(torch.zeros(1, self.batch_size, self.word_gru_hidden))        


# ## Sentence Attention model with bias

# In[6]:


class AttentionSentRNN(nn.Module):
    
    
    def __init__(self, batch_size, sent_gru_hidden, word_gru_hidden, n_classes, bidirectional= True):        
        
        super(AttentionSentRNN, self).__init__()
        
        self.batch_size = batch_size
        self.sent_gru_hidden = sent_gru_hidden
        self.n_classes = n_classes
        self.word_gru_hidden = word_gru_hidden
        self.bidirectional = bidirectional
        
        
        if bidirectional == True:
            self.sent_gru = nn.GRU(2 * word_gru_hidden, sent_gru_hidden, bidirectional= True)        
            self.weight_W_sent = nn.Parameter(torch.Tensor(2* sent_gru_hidden ,2* sent_gru_hidden))
            self.bias_sent = nn.Parameter(torch.Tensor(2* sent_gru_hidden,1))
            self.weight_proj_sent = nn.Parameter(torch.Tensor(2* sent_gru_hidden, 1))
            self.final_linear = nn.Linear(2* sent_gru_hidden, n_classes)
        else:
            self.sent_gru = nn.GRU(word_gru_hidden, sent_gru_hidden, bidirectional= True)        
            self.weight_W_sent = nn.Parameter(torch.Tensor(sent_gru_hidden ,sent_gru_hidden))
            self.bias_sent = nn.Parameter(torch.Tensor(sent_gru_hidden,1))
            self.weight_proj_sent = nn.Parameter(torch.Tensor(sent_gru_hidden, 1))
            self.final_linear = nn.Linear(sent_gru_hidden, n_classes)
        self.softmax_sent = nn.Softmax()
        self.final_softmax = nn.Softmax()
        self.weight_W_sent.data.uniform_(-0.1, 0.1)
        self.weight_proj_sent.data.uniform_(-0.1,0.1)
        
        
    def forward(self, word_attention_vectors, state_sent):
        output_sent, state_sent = self.sent_gru(word_attention_vectors, state_sent)        
        sent_squish = batch_matmul_bias(output_sent, self.weight_W_sent,self.bias_sent, nonlinearity='tanh')
        sent_attn = batch_matmul(sent_squish, self.weight_proj_sent)
        sent_attn_norm = self.softmax_sent(sent_attn.transpose(1,0))
        sent_attn_vectors = attention_mul(output_sent, sent_attn_norm.transpose(1,0))        
        # final classifier
        final_map = self.final_linear(sent_attn_vectors.squeeze(0))
        return F.log_softmax(final_map), state_sent, sent_attn_norm
    
    def init_hidden(self):
        if self.bidirectional == True:
            return Variable(torch.zeros(2, self.batch_size, self.sent_gru_hidden))
        else:
            return Variable(torch.zeros(1, self.batch_size, self.sent_gru_hidden))   


# ## Functions to train the model

# In[7]:


word_attn = AttentionWordRNN(batch_size=64, num_tokens=81132, embed_size=300, 
                             word_gru_hidden=100, bidirectional= True)


# In[8]:


sent_attn = AttentionSentRNN(batch_size=64, sent_gru_hidden=100, word_gru_hidden=100, 
                             n_classes=10, bidirectional= True)


# In[9]:


def train_data(mini_batch, targets, word_attn_model, sent_attn_model, word_optimizer, sent_optimizer, criterion):
    state_word = word_attn_model.init_hidden().cuda()
    state_sent = sent_attn_model.init_hidden().cuda()
    max_sents, batch_size, max_tokens = mini_batch.size()
    word_optimizer.zero_grad()
    sent_optimizer.zero_grad()
    s = None
    for i in range(max_sents):
        _s, state_word, _ = word_attn_model(mini_batch[i,:,:].transpose(0,1), state_word)
        if(s is None):
            s = _s
        else:
            s = torch.cat((s,_s),0)            
    y_pred, state_sent, _ = sent_attn_model(s, state_sent)
    loss = criterion(y_pred.cuda(), targets) 
    loss.backward()
    
    word_optimizer.step()
    sent_optimizer.step()
    
    return loss.data[0]


# In[10]:


def get_predictions(val_tokens, word_attn_model, sent_attn_model):
    max_sents, batch_size, max_tokens = val_tokens.size()
    state_word = word_attn_model.init_hidden().cuda()
    state_sent = sent_attn_model.init_hidden().cuda()
    s = None
    for i in range(max_sents):
        _s, state_word, _ = word_attn_model(val_tokens[i,:,:].transpose(0,1), state_word)
        if(s is None):
            s = _s
        else:
            s = torch.cat((s,_s),0)            
    y_pred, state_sent, _ = sent_attn_model(s, state_sent)    
    return y_pred


# In[11]:


learning_rate = 1e-1
momentum = 0.9
word_optmizer = torch.optim.SGD(word_attn.parameters(), lr=learning_rate, momentum= momentum)
sent_optimizer = torch.optim.SGD(sent_attn.parameters(), lr=learning_rate, momentum= momentum)
criterion = nn.NLLLoss()


# In[12]:


word_attn.cuda()


# In[13]:


sent_attn.cuda()


# ## Loading the data

# In[14]:

data_path = ROOT_PATH + "data/imdb_final.json"
d = pd.read_json(data_path)


# In[15]:


d['rating'] = d['rating'] - 1


# In[16]:


#from keras.preprocessing.sequence import pad_sequences
from sklearn.cross_validation import train_test_split


# In[17]:


d = d[['tokens','rating']]


# In[18]:


X = d.tokens
y = d.rating


# In[19]:


X_train, X_test, y_train, y_test = train_test_split(X.values, y.values, test_size = 0.3, random_state= 42)


# In[20]:



# In[21]:


def pad_batch(mini_batch):
    mini_batch_size = len(mini_batch)
    max_sent_len = int(np.mean([len(x) for x in mini_batch]))
    max_token_len = int(np.mean([len(val) for sublist in mini_batch for val in sublist]))
    main_matrix = np.zeros((mini_batch_size, max_sent_len, max_token_len), dtype= np.int)
    for i in range(main_matrix.shape[0]):
        for j in range(main_matrix.shape[1]):
            for k in range(main_matrix.shape[2]):
                try:
                    main_matrix[i,j,k] = mini_batch[i][j][k]
                except IndexError:
                    pass
    return Variable(torch.from_numpy(main_matrix).cuda().transpose(0,1))


# In[22]:


def accuracy_mini_batch(tokens, labels, word_attn, sent_attn):
    y_pred = get_predictions(tokens, word_attn, sent_attn)
    _, y_pred = torch.max(y_pred, 1)
    correct = np.ndarray.flatten(y_pred.data.cpu().numpy())
    labels = np.ndarray.flatten(labels.data.cpu().numpy())
    num_correct = sum(correct == labels)
    return float(num_correct) / len(correct)


# In[23]:


def accuracy_full_batch(tokens, labels, mini_batch_size, word_attn, sent_attn):
    p = []
    l = []
    g = gen_minibatch(tokens, labels, mini_batch_size)
    for token, label in g:
        y_pred = get_predictions(token.cuda(), word_attn, sent_attn)
        _, y_pred = torch.max(y_pred, 1)
        p.append(np.ndarray.flatten(y_pred.data.cpu().numpy()))
        l.append(np.ndarray.flatten(label.data.cpu().numpy()))
    p = [item for sublist in p for item in sublist]
    l = [item for sublist in l for item in sublist]
    p = np.array(p)
    l = np.array(l)
    num_correct = sum(p == l)
    return float(num_correct)/ len(p)


# In[24]:


def data(mini_batch, targets, word_attn_model, sent_attn_model):
    state_word = word_attn_model.init_hidden().cuda()
    state_sent = sent_attn_model.init_hidden().cuda()
    max_sents, batch_size, max_tokens = mini_batch.size()
    s = None
    for i in range(max_sents):
        _s, state_word, _ = word_attn_model(mini_batch[i,:,:].transpose(0,1), state_word)
        if(s is None):
            s = _s
        else:
            s = torch.cat((s,_s),0)            
    y_pred, state_sent,_ = sent_attn_model(s, state_sent)
    loss = criterion(y_pred.cuda(), targets)     
    return loss.data[0]


# In[25]:


def iterate_minibatches(inputs, targets, batchsize, shuffle=False):
    assert inputs.shape[0] == targets.shape[0]
    if shuffle:
        indices = np.arange(inputs.shape[0])
        np.random.shuffle(indices)
    for start_idx in range(0, inputs.shape[0] - batchsize + 1, batchsize):
        if shuffle:
            excerpt = indices[start_idx:start_idx + batchsize]
        else:
            excerpt = slice(start_idx, start_idx + batchsize)
        yield inputs[excerpt], targets[excerpt]


# In[26]:


def gen_minibatch(tokens, labels, mini_batch_size, shuffle= True):
    for token, label in iterate_minibatches(tokens, labels, mini_batch_size, shuffle= shuffle):
        token = pad_batch(token)
        yield token.cuda(), Variable(torch.from_numpy(label), requires_grad= False).cuda()    


# In[27]:


def check_val_loss(val_tokens, val_labels, mini_batch_size, word_attn_model, sent_attn_model):
    val_loss = []
    for token, label in iterate_minibatches(val_tokens, val_labels, mini_batch_size, shuffle= True):
        val_loss.append(data(pad_batch(token).cuda(), Variable(torch.from_numpy(label), requires_grad= False).cuda(),
                                  word_attn_model, sent_attn_model))
    return np.mean(val_loss)


# In[28]:



def timeSince(since):
    now = time.time()
    s = now - since
    m = math.floor(s / 60)
    s -= m * 60
    return '%dm %ds' % (m, s)


# Training
def train_early_stopping(mini_batch_size, X_train, y_train, X_test, y_test, word_attn_model, sent_attn_model, 
                         word_attn_optimiser, sent_attn_optimiser, loss_criterion, num_epoch, 
                         print_val_loss_every = 1000, print_loss_every = 50):
    start = time.time()
    loss_full = []
    loss_epoch = []
    accuracy_epoch = []
    loss_smooth = []
    accuracy_full = []
    epoch_counter = 0
    g = gen_minibatch(X_train, y_train, mini_batch_size)
    for i in range(1, num_epoch + 1):
        try:
            tokens, labels = next(g)
            loss = train_data(tokens, labels, word_attn_model, sent_attn_model, word_attn_optimiser, sent_attn_optimiser, loss_criterion)
            acc = accuracy_mini_batch(tokens, labels, word_attn_model, sent_attn_model)
            accuracy_full.append(acc)
            accuracy_epoch.append(acc)
            loss_full.append(loss)
            loss_epoch.append(loss)
            # print loss every n passes
            if i % print_loss_every == 0:
                print('Loss at %d minibatches, %d epoch,(%s) is %f' %(i, epoch_counter, timeSince(start), np.mean(loss_epoch)))
                print ('Accuracy at %d minibatches is %f' % (i, np.mean(accuracy_epoch)))
            # check validation loss every n passes
            if i % print_val_loss_every == 0:
                val_loss = check_val_loss(X_test, y_test, mini_batch_size, word_attn_model, sent_attn_model)
                print('Average training loss at this epoch..minibatch..%d..is %f' % (i, np.mean(loss_epoch)))
                print('Validation loss after %d passes is %f' %(i, val_loss))
                if val_loss > np.mean(loss_full):
                    print('Validation loss is higher than training loss at %d is %f , stopping training!' % (i, val_loss))
                    print('Average training loss at %d is %f' % (i, np.mean(loss_full)))
        except StopIteration:
            epoch_counter += 1
            print('Reached %d epocs' % epoch_counter)
            print('i %d' % i)
            g = gen_minibatch(X_train, y_train, mini_batch_size)
            loss_epoch = []
            accuracy_epoch = []
    return loss_full


if __name__ == '__main__':
    loss_full= train_early_stopping(64, X_train, y_train, X_test, y_test, word_attn, sent_attn, word_optmizer, sent_optimizer,
                                criterion, 5000, 1000, 50)
    accuracy_full_batch(X_test, y_test, 64, word_attn, sent_attn)
    accuracy_full_batch(X_train, y_train, 64, word_attn, sent_attn)

