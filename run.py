import os
from request import DataProvider
from beam_stack import BeamForming
from pyrocko import model
from pyrocko import io
from pyrocko.guts import Object, Dict, String
from util import create_directory
from request import DataProvider, CakeTiming
import store_creator
import logging
from array_map import ArrayMap


pjoin = os.path.join

logging.basicConfig(level='INFO')
logger = logging.getLogger('run')

stores_superdir = 'stores'
array_data = 'array_data'
event_fn = 'event.pf'
km = 1000.

class StoreMapper(Object):
    mapping = Dict.T(String.T(), String.T())

def one_or_error(items):
    e = list(items)
    if len(e)>1:
        raise Exception('more than one item in list. Can only handle one')
    else:
        return e[0]

def one_2_list(items):
    if not isinstance(items, list):
        return [items]


def init(args):
    events = list(model.Event.load_catalog(args.events))
    if args.name and len(events)>1:
        logger.warn("Cannot use defined name if list of events. Will"
                        " use event names instead")
    for i_e, e in enumerate(events):
        if e.name:
            name = e.name
        elif args.name:
            name = args.name
            e.name = name
        else:
            logger.warn("event name is empty. Skipping...")
            continue

        create_directory(name, args.force)
        create_directory(name, args.force)

        model.Event.dump_catalog([e], pjoin(name, event_fn))
        if args.download:
            download(args, event=e, prefix=name)
        logger.info('.' * 30)
        logger.info('Prepared project directory %s for you' % name)

def download(args, event=None, prefix=''):
    if not event:
        event = model.Event.load_catalog(event_fn)
        event = one_or_error(event)
    provider = DataProvider()
    try:
        settings = args.download_settings
        provider.download(event, settings=settings)
    except (AttributeError, TypeError):
        e = event
        provider = DataProvider()
        tmin = CakeTiming(phase_selection='first(p|P|PP)-80', fallback_time=100.)
        tmax = CakeTiming(phase_selection='first(p|P|PP)+120', fallback_time=600.)
        provider.download(e, timing=(tmin, tmax), prefix=prefix, dump_config=True)


def beam(args):
    """Uses tmin timing object, without the offset to calculate the beam"""
    event = list(model.Event.load_catalog(event_fn))
    assert len(event)==1
    event = event[0]
    provider = DataProvider.load(filename='request.yaml')
    array_centers = []
    for array_id in provider.use:
        directory = pjoin(array_data, array_id)
        traces = io.load(pjoin(directory, 'traces.mseed'))
        stations = model.load_stations(pjoin(directory, 'stations.pf'))
        bf = BeamForming(stations, traces, normalize=args.normalize)
        bf.process(event=event,
                   timing=provider.timings[array_id].timings[0],
                   fn_dump_center=pjoin(directory, 'array_center.pf'),
                   fn_beam=pjoin(directory, 'beam.mseed'),
                   station=array_id)
        if args.plot:
            bf.plot(fn=pjoin(directory, 'beam_shifts.png'))

        array_centers.append(bf.station_c)

    # how to define map dimensions?
    #map = ArrayMap(stations=array_centers,
    #               station_label_mapping=provider.use,
    #               event=event)
    #map.save(args.map_filename)

def propose_stores(args):
    from get_bounds import get_bounds
    store_mapper = StoreMapper()
    if args.events:
        events = list(model.Event.load_catalog(args.events))
    else:
        events = list(model.Event.load_catalog(event_fn))

    provider = DataProvider.load(filename='request.yaml')
    for array_id in provider.use:
        directory = pjoin(array_data, array_id)
        station = model.load_stations(pjoin(directory, 'array_center.pf'))
        station = one_or_error(station)
        depths = args.depths.split(':')
        sdmin, sdmax, sddelta = map(float, depths)
        configid = store_creator.propose_store(station, events, superdir=args.store_dir,
                                               source_depth_min=sdmin,
                                               source_depth_max=sdmax,
                                               source_depth_delta=sddelta,
                                               sample_rate=args.sample_rate,
                                               force_overwrite=args.force_overwrite,
                                               run_ttt=args.ttt,
                                               simplify=args.simplify)
        assert len(configid)==1
        configid = configid[0]
        store_mapper.mapping[array_id] = configid

    store_mapper.dump(filename='store_mapping.yaml')

def process(args):
    from guesstimate_depth_v02 import PlotSettings, plot

    store_mapper = StoreMapper.load(filename='store_mapping.yaml')

    provider = DataProvider.load(filename='request.yaml')
    #if args.settings:
    #    settings = PlotSettings.load(filename=args.plot_settings)
    #else:

    for array_id in provider.use:

        subdir = pjoin(array_data, array_id)
        settings_fn = pjoin(subdir, 'plot_settings.yaml')
        if os.path.isfile(settings_fn) and not args.overwrite_settings:
            settings = PlotSettings.load(filename=pjoin(settings_fn))
        else:
            settings = PlotSettings.from_argument_parser(args)
            settings.trace_filename = pjoin(subdir, 'beam.mseed')
            settings.station_filename = pjoin(subdir, 'array_center.pf')
            settings.store_superdirs = [stores_superdir]
            settings.store_id = store_mapper.mapping[array_id]
            settings.save_as = pjoin('array_data', array_id, '%s.png'%array_id)
            settings.force_nearest_neighbor = args.force_nearest_neighbor
            settings.dump(filename=settings_fn)
        plot(settings, show=args.show)

def get_bounds(args):
    from get_bounds import get_bounds

    e = list(model.Event.load_catalog(args.events))
    directory = pjoin('array_data', args.array_id)
    stations = model.load_stations(pjoin(directory, 'array_center.pf'))
    get_bounds(stations, events=e, show_fig=True, km=True)

if __name__=='__main__':
    import argparse

    parser = argparse.ArgumentParser('What was the depth, again?', add_help=False)
    parser.add_argument('--log', required=False, default='INFO')

    sp = parser.add_subparsers(dest='cmd')
    init_parser = sp.add_parser('init', help='create a new project')#, parents=[parser])
    init_parser.add_argument('--events',
                             help='Event you don\'t know the depth of',
                             required=True)
    init_parser.add_argument('--name', help='name')
    init_parser.add_argument('--download',
                            action='store_true',
                            default=False,
                            help='download available data right away.')
    init_parser.add_argument('--force',
                            action='store_true',
                            default=False,
                            help='force overwrite')

    download_parser = sp.add_parser('download', help='Download data')#, parents=[parser])
    download_parser.add_argument('--download',
                                help='download available data',
                                default=False,
                                action='store_true')
    download_parser.add_argument('--settings',
                                help='Load download settings.',
                                dest='download_settings',
                                default=False)

    beam_parser = sp.add_parser('beam', help='Beam forming')#, parents=[parser])
    beam_parser.add_argument('--map_filename', help='filename of map',
                            default='map.png')
    beam_parser.add_argument('--normalize',
                            help='normlize by standard deviation of trace',
                            action='store_true',
                            default=True)
    beam_parser.add_argument('--plot',
                            help='create plots showing stations and store them '
                            'in sub-directories',
                            action='store_true',
                            default=False)

    store_parser = sp.add_parser('stores', help='Propose GF stores')#, parents=[parser])
    store_parser.add_argument('--super-dir',
                                dest='store_dir',
                                help='super directory where to search/create stores',
                                default='stores')
    store_parser.add_argument('--depths', help='zmin:zmax:deltaz [km]', required=True)
    store_parser.add_argument('--sampling-rate', dest='sample_rate', type=float,
                                help='samppling rate store [Hz]. Default 10',
                                default=10.)
    store_parser.add_argument('--force-store',
                                dest='force_overwrite',
                                help='overwrite existent stores',
                                action='store_false')
    store_parser.add_argument('--events',
                                dest='events',
                                help='create stores that are suitable for all events in this file')
    store_parser.add_argument('--ttt',
                                dest='ttt',
                                help='also generate travel time tables.',
                                action='store_true')
    store_parser.add_argument('--simplify',
                                help='Simplify model to increase performance '
                              'and in case of QSEIS lmax too small error.',
                                action='store_true')

    process_parser = sp.add_parser('process', help='Create images')#, parents=[parser])
    process_parser.add_argument('--array_id',
                                help='array_id to process',
                                required=False,
                                default=False)
    process_parser.add_argument('--settings',
                                help='settings file',
                                default=False,
                                required=False)
    #process_parser.add_argument('--trace', help='name of file containing trace',
    #                           required=True)
    #process_parser.add_argument('--station',
    #                    help='name of file containing station information',
    #                    required=True)
    #process_parser.add_argument('--event',
    #                    help='name of file containing event catalog',
    #                    required=True)
    process_parser.add_argument('--store',
                        help='name of store id',
                        dest='store_id',
                        required=False)
    #process_parser.add_argument('--pick',
    #                    help='name of file containing p marker',
    #                    required=True)
    process_parser.add_argument('--depth',
                        help='assumed source depth [km]',
                        default=10.,
                        required=False)
    process_parser.add_argument('--depths',
                        help='testing depths in km. zstart:zstop:delta, default 0:15:1',
                        default='0:15:1',
                        required=False)
    process_parser.add_argument('--quantity',
                        help='velocity|displacement',
                        default='velocity',
                        required=False)
    process_parser.add_argument('--filter',
                        help='4th order butterw. default: "0.7:4.5"',
                        default="0.7:4.5",
                        required=False)
    process_parser.add_argument('--correction',
                        help='correction in time [s]',
                        default=0,
                       required=False)

    # MUSS WIEDER REIN NACH GRUPPIERUNG
    process_parser.add_argument('--normalize',
                        help='normalize traces to 1',
                        action='store_true',
                        required=False)
    process_parser.add_argument('--skip-true',
                        help='if true, do not plot recorded and the assigned synthetic trace on top of each other',
                        dest='skip_true',
                        action='store_true',
                        required=False)
    process_parser.add_argument('--show',
                        help='show matplotlib plots after each step',
                        action='store_true',
                        required=False)
    process_parser.add_argument('--force-nearest-neighbor',
                        help='handles OOB',
                        dest='force_nearest_neighbor',
                        default=False,
                        action='store_true',
                        required=False)
    #process_parser.add_argument('--out_filename',
    #                    help='file to store image',
    #                    required=False)
    process_parser.add_argument('--print-parameters', dest='print_parameters',
                        help='creates a text field giving the used parameters',
                        required=False)
    process_parser.add_argument('--overwrite-settings', dest='overwrite_settings',
                        help='overwrite former settings files', default=False,
                        action='store_true', required=False)

    bounds_parser = sp.add_parser('bounds', help='get bounds of array vs catalog of events. '
                                  'Helpful when generating stores for entire catalogs.')#, parents=[parser])
    bounds_parser.add_argument('--events',
                        help='events filename',
                        required=True)

    bounds_parser.add_argument('--array-id',
                        help='array id',
                        dest='array_id',
                        required=True)

    args = parser.parse_args()

    logging.basicConfig(level=args.log.upper())

    if args.cmd == 'init':
        init(args)

    if args.cmd == 'download':
        download(args)

    if args.cmd == 'stores':
        propose_stores(args)

    if args.cmd == 'beam':
        beam(args)

    if args.cmd == 'process':
        process(args)

    if args.cmd == 'bounds':
        get_bounds(args)

