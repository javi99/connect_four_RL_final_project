import jax.numpy as np
import numpy as onp
import matplotlib.pyplot as plt
from jax import value_and_grad, jit
from jax.lax import stop_gradient


def zero_sum_loss(predict, s1, a_, r_, s2, paras= {}):
    nets1 = predict(s1)
    nets2 = predict(s2)
    Q_1 = np.sum(nets1*a_, axis = 1)
    rt = np.reshape(r_,[-1])
    Q_2 = rt - paras['gamma'] * np.amax(nets2,axis=1)*(1-np.abs(rt))
    Q_2 = stop_gradient(Q_2)
    return np.mean((Q_1-Q_2)**2)



class AbstractAgent():
    """abstract interface for a trainable deep agent"""
    
    def __init__(self):
        """init sha.l build the computation graph and all relevant quantities
        implementations will probably need many parameters here"""
        raise NotImplementedError()
    
    def prediction(self, state):
        """gives the prediction of the agent as a vector of reals"""
        raise NotImplementedError()
    
    def train(self, mem, minibatchSize = 10):
        """performs one step of training using a coompatible memory object"""
        raise NotImplementedError()
    
    def training_move(self, state):
        """gives the next move of the AI, with exploration"""
        raise NotImplementedError()
    

class FeedforwardAgent(AbstractAgent):
    """directly computes action-relevant quantities useing feedforward NNSs"""
    
    def __init__(self,state_shape, hidden_shape,  action_shape, 
            nonlinearity = ['relu','relu','relu','sigmoid'],\
            used_loss = zero_sum_loss, gamma = 0.99,\
            model_name = "testNet", stop_gradient = True,
            action_noise=0.01, learning_rate=0.001):
        """init shall build the computation graph and all relevant quantities
        implementations will probably need many parameters here"""
        """
        builds the neural network using the shape that is stored in the global variables
        :return: None
        """
        self.stop_gradient = stop_gradient
        self.model_name = model_name
        self.output_shape = action_shape
        self.nonlinearity = nonlinearity
        self.shapes = [state_shape]+hidden_shape+[action_shape]
        self.used_loss = used_loss
        self.loss_paras = {}
        self.loss_paras['gamma'] = gamma
        self.action_noise = action_noise
        self.epsilon = 0.1
        self.learning_rate = learning_rate
        self.variables = None
        layers = []
        from jax.example_libraries import stax
        for i, sh in enumerate(self.shapes[1:]):
            print(f"layer shape: {sh}")
            if len(sh) ==3:
                ks = [self.shapes[i][0] - sh[0]+1, 
                    self.shapes[i][1] - sh[1]+1]
                layers += [stax.Conv(sh[-1], ks)]
                print("conv")
            else:
                assert len(sh) == 1
                if len(self.shapes[i]) == 3:
                    layers += [stax.Flatten]
                    print("flatten to go from conv to dense")
                layers += [stax.Dense(*sh)]
                print("dense")
            if nonlinearity[i] == 'relu':
                layers += [stax.Relu]
                print("relu")
        self._initop, predict = stax.serial(*layers)
        self._predict = jit(predict)
        print("shapes:", self.shapes)

        self._loss = lambda params, inp: self.used_loss(lambda s: self._predict(params, s), *inp[:4], paras=self.loss_paras)
        self._opt_init = lambda x:x
        self._get_params  = lambda x:x
        self._initialized_optimizer = False
        self._steps = 0
        def update(i, opt_state, batch):
            var = opt_state
            l, grad = value_and_grad(self._loss)(var, batch)
            nvar = tuple()
            for j in range(len(opt_state)):
                temp = tuple()
                for k in range(len(opt_state[j])):
                    temp += (var[j][k] - self.learning_rate*grad[j][k],)
                nvar += (temp,)
            return l, nvar
            var = self._get_params(opt_state)
            l, grad = value_and_grad(self._loss)(var, batch)
            opt_state = self._train_step(i, grad, opt_state)
            return l, opt_state
        self._update = jit(update)

    def init_variables(self, rng):
        _, self.variables = self._initop(rng, (-1,)+self.shapes[0])
        print([len(v) for v in self.variables])
        print([[np.std(l) for l in v] for v in self.variables])

    def loss(self, batch):
        return self._loss(self.variables, batch)

    def training_move(self, state):
        #returns the action the agent performs in an epsilon greedy policy
        a = onp.zeros(7)
        if onp.random.rand() < self.epsilon:
            a[onp.random.randint(0,7)] = 1
            return a
        else:
            c = self._predict(self.variables, state)
        if self.action_noise != 0:
            c += onp.random.normal(size=c.shape)*self.action_noise
        a[onp.argmax(c)] = 1
        return a
    
    def prediction(self, state):
        #returns the raw predictions the agent makes
        c = self._predict(self.variables, state)
        return c    
        
    def train(self, mem, minibatchSize = 10):
        #apply one gradient descent step from a historic sample, returns loss
        if not self._initialized_optimizer:
            self._opt_state = self._opt_init(self.variables)
            self._initialized_optimizer = True
        batch = None
        batch = mem.get_minibatch(size=minibatchSize)
        l, self._opt_state = self._update(self._steps, self._opt_state, batch)
        self.variables = self._get_params(self._opt_state)
        self._steps += 1
        return l

    def show_kernel(self):
        W = self.variables[0][0][:,:,0,:]
        im = np.zeros((19,19))
        for i in range(16):
            px = int(i/4)
            py = i%4
            im[px*5:px*5+4, py*5:py*5+4] = W[:,:,i]
        plt.imshow(im, interpolation = "nearest", cmap='hot')

    def think_ahead(self, game, player, steps, noise = 0.):
        #simulates the next steps assuming a zero sum game
        if steps == 0:
            return self.prediction(game.preprocessedState(player))[0,:]
        else:
            values = onp.zeros(self.shapes[-1])
            for i in range(self.shapes[-1][0]):
                r = game.play(player, i)
                if r != 0:
                    values[i] = r
                else:
                    values[i] = -self.loss_paras['gamma']*onp.amax(self.think_ahead(game, player*(-1), steps-1))
                if r != -1:
                    game.undoPlay(i)
            return values+onp.random.normal(size=values.shape)*noise


            
#TODO: this must be made better!
def compute_avg_loss(agent, mem, miniBatchSize = 50):
    lmax = -10.
    lmin = 10.
    lavg = 0.
    N_samps = 2000
    for i in range(N_samps):
        l = None
        batch = mem.get_minibatch(size=miniBatchSize)
        l = agent.loss(batch)
        lmax = max(l,lmax)
        lmin = min(l,lmin)
        lavg += l
    lavg /= N_samps
    print("min loss, max loss, avg loss")
    print(lmin, lmax, lavg)
    return lavg

