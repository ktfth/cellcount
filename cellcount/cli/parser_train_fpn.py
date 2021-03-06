from argparse import ArgumentDefaultsHelpFormatter


def func(args, parser):
    from os.path import basename, join, isfile
    from glob import glob

    import torch
    import torch.optim as optim
    from torch.utils.data import DataLoader

    import visdom

    from cellcount.utils import (ChunkSampler, ImageWithMask, train, test,
                                 get_val_example, push_epoch_image,
                                 save_checkpoint)
    from cellcount.models import FPN
    from cellcount.losses import fpn_loss

    if args.display:
        vis = visdom.Visdom(port=8097)

    BBBC = args.dataset
    BATCH_SIZE = args.batch_size
    gpu_dtype = torch.cuda.FloatTensor

    image_dir = glob(join(BBBC, '*images/'))[0]
    truth_dir = glob(join(BBBC, '*ground_truth/'))[0]

    train_data = ImageWithMask(image_dir)
    
    def assign_gt(fn):
        flags = fn.split('_')
        flags[1] = 'A' + flags[1][1:]
        flags[3] = 'F1'
        return '_'.join(flags)
    
    train_data.imgs = [(i, join(truth_dir, assign_gt(basename(i))))
                       for i, _ in train_data.imgs]
    
    NUM_TRAIN = len(train_data.imgs) // 2
    NUM_VAL = len(train_data.imgs) - NUM_TRAIN

    loader_train = DataLoader(train_data, batch_size=BATCH_SIZE,
                              sampler=ChunkSampler(NUM_TRAIN, 0))
    loader_val = DataLoader(train_data, batch_size=BATCH_SIZE,
                            sampler=ChunkSampler(NUM_VAL, NUM_TRAIN))

    x_var, y_var = get_val_example(loader_val, gpu_dtype)
    _, _, h, w = x_var.size()

    fpn = FPN(h, w).type(gpu_dtype)
    lr = args.learning_rate

    if args.cont and isfile('fpn_checkpoint.pth.tar'):
        print('Continuing from previous checkpoint...')
        checkpoint = torch.load('fpn_model_best.pth.tar')
        fpn.load_state_dict(checkpoint['fpn'])
        optimizer = optim.Adam(fpn.parameters(), lr=lr)
        optimizer.load_state_dict(checkpoint['optimizer'])
        best_loss = checkpoint['avg_val_loss']
    else:
        optimizer = optimizer = optim.Adam(fpn.parameters(), lr=lr)
        best_loss = 1E6

    epochs = args.num_epochs
    for epoch in range(epochs):
        print('epoch: %s' % epoch)

        if epoch > 0 and (epoch % 20 == 0):
            for param_group in optimizer.param_groups:
                param_group['lr'] *= .5

        train(loader_train, fpn, fpn_loss, optimizer, gpu_dtype)
        val_loss = test(loader_val, fpn, fpn_loss, gpu_dtype)

        is_best = val_loss < best_loss
        if is_best:
            best_loss = val_loss

        save_checkpoint({
            'epoch': epoch,
            'fpn': fpn.state_dict(),
            'avg_val_loss': val_loss,
            'optimizer': optimizer.state_dict(),
        }, is_best, name='fpn')

        if args.display:
            push_epoch_image(x_var, y_var, fpn, vis, epoch)


def configure_parser(sub_parsers):
    help = 'Train FPN'
    p = sub_parsers.add_parser('train_fpn', description=help, help=help,
                               formatter_class=ArgumentDefaultsHelpFormatter)
    p.add_argument('--dataset', type=str, help="Path to BBBC dataset",
                   required=True)
    p.add_argument('--num-epochs', type=int, help="Number of epochs",
                   default=1)
    p.add_argument('--batch-size', type=int, help="Batch size", default=5)
    p.add_argument('--learning-rate', type=float, help="Learning rate",
                   default=1E-4)
    p.add_argument('--cont', help="Continue from saved state",
                   action='store_true')
    p.add_argument('--display', help="Display via Visdom",
                   action='store_true')
    p.set_defaults(func=func)
