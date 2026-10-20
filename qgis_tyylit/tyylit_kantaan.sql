-- QGIS-oletustyylit kannan mittaustasoille (tehty: qgis_tyylit/tee_tyylit.py).
-- Aja kerran (Supabase: SQL Editor). Tämän jälkeen QGIS käyttää tyylejä automaattisesti,
-- kun taso lisätään. Jo lisätty taso: Layer Properties -> Style -> Load Style -> From Database.
CREATE TABLE IF NOT EXISTS public.layer_styles (
    id SERIAL PRIMARY KEY,
    f_table_catalog varchar,
    f_table_schema varchar,
    f_table_name varchar,
    f_geometry_column varchar,
    stylename text,
    styleqml xml,
    stylesld xml,
    useasdefault boolean,
    description text,
    owner varchar(63) DEFAULT CURRENT_USER,
    ui xml,
    update_time timestamp DEFAULT CURRENT_TIMESTAMP,
    type varchar,
    r_raster_column varchar
);
-- QGIS hakee tyylit myös tällä sarakkeella; vanhemman QGIS:n tekemästä taulusta se voi puuttua
ALTER TABLE public.layer_styles ADD COLUMN IF NOT EXISTS r_raster_column varchar;

UPDATE public.layer_styles SET useasdefault = false
    WHERE f_table_schema = 'public' AND f_table_name = 'asemapisteet';
DELETE FROM public.layer_styles
    WHERE f_table_schema = 'public' AND f_table_name = 'asemapisteet' AND stylename = 'Tietokanta';
INSERT INTO public.layer_styles
    (f_table_catalog, f_table_schema, f_table_name, f_geometry_column, stylename, styleqml, useasdefault,
     description)
VALUES (current_database(), 'public', 'asemapisteet', 'geom', 'Tietokanta', XMLPARSE(DOCUMENT $qml$<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis labelsEnabled="1" layerType="Vector" styleCategories="Symbology|Labeling" version="4.2.1-Belém do Pará">
  <renderer-v2 attr="laatuluokka" enableorderby="0" forceraster="0" referencescale="-1" symbollevels="0" type="categorizedSymbol">
    <categories>
      <category label="Erinomainen" render="true" symbol="0" type="string" uuid="{598ec8d8-d176-48d2-a54d-dc821ac53b04}" value="Erinomainen"/>
      <category label="Hyvä" render="true" symbol="1" type="string" uuid="{9e2c0824-ddcc-468f-ae49-f58ed325be7a}" value="Hyvä"/>
      <category label="Tyydyttävä" render="true" symbol="2" type="string" uuid="{1d7cf1b0-a63c-4ced-bdcd-05c4b44acf3f}" value="Tyydyttävä"/>
      <category label="Heikko" render="true" symbol="3" type="string" uuid="{9f5ed757-3bcd-4c06-a335-3cd162512950}" value="Heikko"/>
      <category label="Huono" render="true" symbol="4" type="string" uuid="{f70ac38c-bd1c-4f3d-bef8-682082194fd8}" value="Huono"/>
      <category label="Ei laskettavissa" render="true" symbol="5" type="string" uuid="{a5a10872-e5b0-4cfb-bcc9-b188b708c54f}" value="Ei laskettavissa"/>
    </categories>
    <symbols>
      <symbol alpha="1" clip_to_extent="1" force_rhr="0" frame_rate="10" is_animated="0" name="0" type="marker">
        <data_defined_properties>
          <Option type="Map">
            <Option name="name" type="QString" value=""/>
            <Option name="properties"/>
            <Option name="type" type="QString" value="collection"/>
          </Option>
        </data_defined_properties>
        <layer class="SimpleMarker" enabled="1" id="{e7af6575-406d-4a96-aa9e-49d3c8725665}" locked="0" pass="0">
          <Option type="Map">
            <Option name="angle" type="QString" value="0"/>
            <Option name="cap_style" type="QString" value="square"/>
            <Option name="color" type="QString" value="0,0,0,255,rgb:0,0,0,1"/>
            <Option name="horizontal_anchor_point" type="QString" value="1"/>
            <Option name="joinstyle" type="QString" value="bevel"/>
            <Option name="name" type="QString" value="triangle"/>
            <Option name="offset" type="QString" value="0,0"/>
            <Option name="offset_map_unit_scale" type="QString" value="3x:0,0,0,0,0,0"/>
            <Option name="offset_unit" type="QString" value="MM"/>
            <Option name="outline_color" type="QString" value="35,35,35,255,rgb:0.1372549,0.1372549,0.1372549,1"/>
            <Option name="outline_style" type="QString" value="solid"/>
            <Option name="outline_width" type="QString" value="0.3"/>
            <Option name="outline_width_map_unit_scale" type="QString" value="3x:0,0,0,0,0,0"/>
            <Option name="outline_width_unit" type="QString" value="MM"/>
            <Option name="scale_method" type="QString" value="diameter"/>
            <Option name="size" type="QString" value="7.5"/>
            <Option name="size_map_unit_scale" type="QString" value="3x:0,0,0,0,0,0"/>
            <Option name="size_unit" type="QString" value="MM"/>
            <Option name="vertical_anchor_point" type="QString" value="1"/>
          </Option>
          <data_defined_properties>
            <Option type="Map">
              <Option name="name" type="QString" value=""/>
              <Option name="properties" type="Map">
                <Option name="fillColor" type="Map">
                  <Option name="active" type="bool" value="true"/>
                  <Option name="expression" type="QString" value="array_get(array('#1f77b4', '#ff7f0e', '#9467bd', '#e377c2', '#17becf', '#8c564b', '#393b79', '#bcbd22', '#00796b', '#c51b7d'), (coalesce(&quot;asema_nro&quot;, 1) - 1) % 10)"/>
                  <Option name="type" type="int" value="3"/>
                </Option>
              </Option>
              <Option name="type" type="QString" value="collection"/>
            </Option>
          </data_defined_properties>
        </layer>
        <layer class="SimpleMarker" enabled="1" id="{7d4aca3e-f0dd-4d11-84b0-45b8ea90bf57}" locked="0" pass="0">
          <Option type="Map">
            <Option name="angle" type="QString" value="0"/>
            <Option name="cap_style" type="QString" value="square"/>
            <Option name="color" type="QString" value="0,104,55,255,rgb:0,0.4078431,0.2156863,1"/>
            <Option name="horizontal_anchor_point" type="QString" value="1"/>
            <Option name="joinstyle" type="QString" value="bevel"/>
            <Option name="name" type="QString" value="triangle"/>
            <Option name="offset" type="QString" value="0,0"/>
            <Option name="offset_map_unit_scale" type="QString" value="3x:0,0,0,0,0,0"/>
            <Option name="offset_unit" type="QString" value="MM"/>
            <Option name="outline_color" type="QString" value="35,35,35,255,rgb:0.1372549,0.1372549,0.1372549,1"/>
            <Option name="outline_style" type="QString" value="solid"/>
            <Option name="outline_width" type="QString" value="0.3"/>
            <Option name="outline_width_map_unit_scale" type="QString" value="3x:0,0,0,0,0,0"/>
            <Option name="outline_width_unit" type="QString" value="MM"/>
            <Option name="scale_method" type="QString" value="diameter"/>
            <Option name="size" type="QString" value="4.2"/>
            <Option name="size_map_unit_scale" type="QString" value="3x:0,0,0,0,0,0"/>
            <Option name="size_unit" type="QString" value="MM"/>
            <Option name="vertical_anchor_point" type="QString" value="1"/>
          </Option>
          <data_defined_properties>
            <Option type="Map">
              <Option name="name" type="QString" value=""/>
              <Option name="properties"/>
              <Option name="type" type="QString" value="collection"/>
            </Option>
          </data_defined_properties>
        </layer>
      </symbol>
      <symbol alpha="1" clip_to_extent="1" force_rhr="0" frame_rate="10" is_animated="0" name="1" type="marker">
        <data_defined_properties>
          <Option type="Map">
            <Option name="name" type="QString" value=""/>
            <Option name="properties"/>
            <Option name="type" type="QString" value="collection"/>
          </Option>
        </data_defined_properties>
        <layer class="SimpleMarker" enabled="1" id="{5565f59a-b7a1-474d-a3b2-121517ffac03}" locked="0" pass="0">
          <Option type="Map">
            <Option name="angle" type="QString" value="0"/>
            <Option name="cap_style" type="QString" value="square"/>
            <Option name="color" type="QString" value="0,0,0,255,rgb:0,0,0,1"/>
            <Option name="horizontal_anchor_point" type="QString" value="1"/>
            <Option name="joinstyle" type="QString" value="bevel"/>
            <Option name="name" type="QString" value="triangle"/>
            <Option name="offset" type="QString" value="0,0"/>
            <Option name="offset_map_unit_scale" type="QString" value="3x:0,0,0,0,0,0"/>
            <Option name="offset_unit" type="QString" value="MM"/>
            <Option name="outline_color" type="QString" value="35,35,35,255,rgb:0.1372549,0.1372549,0.1372549,1"/>
            <Option name="outline_style" type="QString" value="solid"/>
            <Option name="outline_width" type="QString" value="0.3"/>
            <Option name="outline_width_map_unit_scale" type="QString" value="3x:0,0,0,0,0,0"/>
            <Option name="outline_width_unit" type="QString" value="MM"/>
            <Option name="scale_method" type="QString" value="diameter"/>
            <Option name="size" type="QString" value="7.5"/>
            <Option name="size_map_unit_scale" type="QString" value="3x:0,0,0,0,0,0"/>
            <Option name="size_unit" type="QString" value="MM"/>
            <Option name="vertical_anchor_point" type="QString" value="1"/>
          </Option>
          <data_defined_properties>
            <Option type="Map">
              <Option name="name" type="QString" value=""/>
              <Option name="properties" type="Map">
                <Option name="fillColor" type="Map">
                  <Option name="active" type="bool" value="true"/>
                  <Option name="expression" type="QString" value="array_get(array('#1f77b4', '#ff7f0e', '#9467bd', '#e377c2', '#17becf', '#8c564b', '#393b79', '#bcbd22', '#00796b', '#c51b7d'), (coalesce(&quot;asema_nro&quot;, 1) - 1) % 10)"/>
                  <Option name="type" type="int" value="3"/>
                </Option>
              </Option>
              <Option name="type" type="QString" value="collection"/>
            </Option>
          </data_defined_properties>
        </layer>
        <layer class="SimpleMarker" enabled="1" id="{7619df57-1e7d-4316-ae65-1f49ccc5d9a2}" locked="0" pass="0">
          <Option type="Map">
            <Option name="angle" type="QString" value="0"/>
            <Option name="cap_style" type="QString" value="square"/>
            <Option name="color" type="QString" value="49,163,84,255,rgb:0.1921569,0.6392157,0.3294118,1"/>
            <Option name="horizontal_anchor_point" type="QString" value="1"/>
            <Option name="joinstyle" type="QString" value="bevel"/>
            <Option name="name" type="QString" value="triangle"/>
            <Option name="offset" type="QString" value="0,0"/>
            <Option name="offset_map_unit_scale" type="QString" value="3x:0,0,0,0,0,0"/>
            <Option name="offset_unit" type="QString" value="MM"/>
            <Option name="outline_color" type="QString" value="35,35,35,255,rgb:0.1372549,0.1372549,0.1372549,1"/>
            <Option name="outline_style" type="QString" value="solid"/>
            <Option name="outline_width" type="QString" value="0.3"/>
            <Option name="outline_width_map_unit_scale" type="QString" value="3x:0,0,0,0,0,0"/>
            <Option name="outline_width_unit" type="QString" value="MM"/>
            <Option name="scale_method" type="QString" value="diameter"/>
            <Option name="size" type="QString" value="4.2"/>
            <Option name="size_map_unit_scale" type="QString" value="3x:0,0,0,0,0,0"/>
            <Option name="size_unit" type="QString" value="MM"/>
            <Option name="vertical_anchor_point" type="QString" value="1"/>
          </Option>
          <data_defined_properties>
            <Option type="Map">
              <Option name="name" type="QString" value=""/>
              <Option name="properties"/>
              <Option name="type" type="QString" value="collection"/>
            </Option>
          </data_defined_properties>
        </layer>
      </symbol>
      <symbol alpha="1" clip_to_extent="1" force_rhr="0" frame_rate="10" is_animated="0" name="2" type="marker">
        <data_defined_properties>
          <Option type="Map">
            <Option name="name" type="QString" value=""/>
            <Option name="properties"/>
            <Option name="type" type="QString" value="collection"/>
          </Option>
        </data_defined_properties>
        <layer class="SimpleMarker" enabled="1" id="{5b223123-05ef-4298-80ea-bb579c25be82}" locked="0" pass="0">
          <Option type="Map">
            <Option name="angle" type="QString" value="0"/>
            <Option name="cap_style" type="QString" value="square"/>
            <Option name="color" type="QString" value="0,0,0,255,rgb:0,0,0,1"/>
            <Option name="horizontal_anchor_point" type="QString" value="1"/>
            <Option name="joinstyle" type="QString" value="bevel"/>
            <Option name="name" type="QString" value="triangle"/>
            <Option name="offset" type="QString" value="0,0"/>
            <Option name="offset_map_unit_scale" type="QString" value="3x:0,0,0,0,0,0"/>
            <Option name="offset_unit" type="QString" value="MM"/>
            <Option name="outline_color" type="QString" value="35,35,35,255,rgb:0.1372549,0.1372549,0.1372549,1"/>
            <Option name="outline_style" type="QString" value="solid"/>
            <Option name="outline_width" type="QString" value="0.3"/>
            <Option name="outline_width_map_unit_scale" type="QString" value="3x:0,0,0,0,0,0"/>
            <Option name="outline_width_unit" type="QString" value="MM"/>
            <Option name="scale_method" type="QString" value="diameter"/>
            <Option name="size" type="QString" value="7.5"/>
            <Option name="size_map_unit_scale" type="QString" value="3x:0,0,0,0,0,0"/>
            <Option name="size_unit" type="QString" value="MM"/>
            <Option name="vertical_anchor_point" type="QString" value="1"/>
          </Option>
          <data_defined_properties>
            <Option type="Map">
              <Option name="name" type="QString" value=""/>
              <Option name="properties" type="Map">
                <Option name="fillColor" type="Map">
                  <Option name="active" type="bool" value="true"/>
                  <Option name="expression" type="QString" value="array_get(array('#1f77b4', '#ff7f0e', '#9467bd', '#e377c2', '#17becf', '#8c564b', '#393b79', '#bcbd22', '#00796b', '#c51b7d'), (coalesce(&quot;asema_nro&quot;, 1) - 1) % 10)"/>
                  <Option name="type" type="int" value="3"/>
                </Option>
              </Option>
              <Option name="type" type="QString" value="collection"/>
            </Option>
          </data_defined_properties>
        </layer>
        <layer class="SimpleMarker" enabled="1" id="{e0fa6d30-2937-4320-8eac-40ff696111a7}" locked="0" pass="0">
          <Option type="Map">
            <Option name="angle" type="QString" value="0"/>
            <Option name="cap_style" type="QString" value="square"/>
            <Option name="color" type="QString" value="254,196,79,255,rgb:0.9960784,0.7686275,0.3098039,1"/>
            <Option name="horizontal_anchor_point" type="QString" value="1"/>
            <Option name="joinstyle" type="QString" value="bevel"/>
            <Option name="name" type="QString" value="triangle"/>
            <Option name="offset" type="QString" value="0,0"/>
            <Option name="offset_map_unit_scale" type="QString" value="3x:0,0,0,0,0,0"/>
            <Option name="offset_unit" type="QString" value="MM"/>
            <Option name="outline_color" type="QString" value="35,35,35,255,rgb:0.1372549,0.1372549,0.1372549,1"/>
            <Option name="outline_style" type="QString" value="solid"/>
            <Option name="outline_width" type="QString" value="0.3"/>
            <Option name="outline_width_map_unit_scale" type="QString" value="3x:0,0,0,0,0,0"/>
            <Option name="outline_width_unit" type="QString" value="MM"/>
            <Option name="scale_method" type="QString" value="diameter"/>
            <Option name="size" type="QString" value="4.2"/>
            <Option name="size_map_unit_scale" type="QString" value="3x:0,0,0,0,0,0"/>
            <Option name="size_unit" type="QString" value="MM"/>
            <Option name="vertical_anchor_point" type="QString" value="1"/>
          </Option>
          <data_defined_properties>
            <Option type="Map">
              <Option name="name" type="QString" value=""/>
              <Option name="properties"/>
              <Option name="type" type="QString" value="collection"/>
            </Option>
          </data_defined_properties>
        </layer>
      </symbol>
      <symbol alpha="1" clip_to_extent="1" force_rhr="0" frame_rate="10" is_animated="0" name="3" type="marker">
        <data_defined_properties>
          <Option type="Map">
            <Option name="name" type="QString" value=""/>
            <Option name="properties"/>
            <Option name="type" type="QString" value="collection"/>
          </Option>
        </data_defined_properties>
        <layer class="SimpleMarker" enabled="1" id="{7dbac57d-d2ad-4b84-a50f-47c1dd11b902}" locked="0" pass="0">
          <Option type="Map">
            <Option name="angle" type="QString" value="0"/>
            <Option name="cap_style" type="QString" value="square"/>
            <Option name="color" type="QString" value="0,0,0,255,rgb:0,0,0,1"/>
            <Option name="horizontal_anchor_point" type="QString" value="1"/>
            <Option name="joinstyle" type="QString" value="bevel"/>
            <Option name="name" type="QString" value="triangle"/>
            <Option name="offset" type="QString" value="0,0"/>
            <Option name="offset_map_unit_scale" type="QString" value="3x:0,0,0,0,0,0"/>
            <Option name="offset_unit" type="QString" value="MM"/>
            <Option name="outline_color" type="QString" value="35,35,35,255,rgb:0.1372549,0.1372549,0.1372549,1"/>
            <Option name="outline_style" type="QString" value="solid"/>
            <Option name="outline_width" type="QString" value="0.3"/>
            <Option name="outline_width_map_unit_scale" type="QString" value="3x:0,0,0,0,0,0"/>
            <Option name="outline_width_unit" type="QString" value="MM"/>
            <Option name="scale_method" type="QString" value="diameter"/>
            <Option name="size" type="QString" value="7.5"/>
            <Option name="size_map_unit_scale" type="QString" value="3x:0,0,0,0,0,0"/>
            <Option name="size_unit" type="QString" value="MM"/>
            <Option name="vertical_anchor_point" type="QString" value="1"/>
          </Option>
          <data_defined_properties>
            <Option type="Map">
              <Option name="name" type="QString" value=""/>
              <Option name="properties" type="Map">
                <Option name="fillColor" type="Map">
                  <Option name="active" type="bool" value="true"/>
                  <Option name="expression" type="QString" value="array_get(array('#1f77b4', '#ff7f0e', '#9467bd', '#e377c2', '#17becf', '#8c564b', '#393b79', '#bcbd22', '#00796b', '#c51b7d'), (coalesce(&quot;asema_nro&quot;, 1) - 1) % 10)"/>
                  <Option name="type" type="int" value="3"/>
                </Option>
              </Option>
              <Option name="type" type="QString" value="collection"/>
            </Option>
          </data_defined_properties>
        </layer>
        <layer class="SimpleMarker" enabled="1" id="{b329872e-b555-4245-ae49-79e1957d54ff}" locked="0" pass="0">
          <Option type="Map">
            <Option name="angle" type="QString" value="0"/>
            <Option name="cap_style" type="QString" value="square"/>
            <Option name="color" type="QString" value="240,59,32,255,rgb:0.9411765,0.2313726,0.1254902,1"/>
            <Option name="horizontal_anchor_point" type="QString" value="1"/>
            <Option name="joinstyle" type="QString" value="bevel"/>
            <Option name="name" type="QString" value="triangle"/>
            <Option name="offset" type="QString" value="0,0"/>
            <Option name="offset_map_unit_scale" type="QString" value="3x:0,0,0,0,0,0"/>
            <Option name="offset_unit" type="QString" value="MM"/>
            <Option name="outline_color" type="QString" value="35,35,35,255,rgb:0.1372549,0.1372549,0.1372549,1"/>
            <Option name="outline_style" type="QString" value="solid"/>
            <Option name="outline_width" type="QString" value="0.3"/>
            <Option name="outline_width_map_unit_scale" type="QString" value="3x:0,0,0,0,0,0"/>
            <Option name="outline_width_unit" type="QString" value="MM"/>
            <Option name="scale_method" type="QString" value="diameter"/>
            <Option name="size" type="QString" value="4.2"/>
            <Option name="size_map_unit_scale" type="QString" value="3x:0,0,0,0,0,0"/>
            <Option name="size_unit" type="QString" value="MM"/>
            <Option name="vertical_anchor_point" type="QString" value="1"/>
          </Option>
          <data_defined_properties>
            <Option type="Map">
              <Option name="name" type="QString" value=""/>
              <Option name="properties"/>
              <Option name="type" type="QString" value="collection"/>
            </Option>
          </data_defined_properties>
        </layer>
      </symbol>
      <symbol alpha="1" clip_to_extent="1" force_rhr="0" frame_rate="10" is_animated="0" name="4" type="marker">
        <data_defined_properties>
          <Option type="Map">
            <Option name="name" type="QString" value=""/>
            <Option name="properties"/>
            <Option name="type" type="QString" value="collection"/>
          </Option>
        </data_defined_properties>
        <layer class="SimpleMarker" enabled="1" id="{9f3ffcfa-5991-40b5-ac6d-b90f948ed106}" locked="0" pass="0">
          <Option type="Map">
            <Option name="angle" type="QString" value="0"/>
            <Option name="cap_style" type="QString" value="square"/>
            <Option name="color" type="QString" value="0,0,0,255,rgb:0,0,0,1"/>
            <Option name="horizontal_anchor_point" type="QString" value="1"/>
            <Option name="joinstyle" type="QString" value="bevel"/>
            <Option name="name" type="QString" value="triangle"/>
            <Option name="offset" type="QString" value="0,0"/>
            <Option name="offset_map_unit_scale" type="QString" value="3x:0,0,0,0,0,0"/>
            <Option name="offset_unit" type="QString" value="MM"/>
            <Option name="outline_color" type="QString" value="35,35,35,255,rgb:0.1372549,0.1372549,0.1372549,1"/>
            <Option name="outline_style" type="QString" value="solid"/>
            <Option name="outline_width" type="QString" value="0.3"/>
            <Option name="outline_width_map_unit_scale" type="QString" value="3x:0,0,0,0,0,0"/>
            <Option name="outline_width_unit" type="QString" value="MM"/>
            <Option name="scale_method" type="QString" value="diameter"/>
            <Option name="size" type="QString" value="7.5"/>
            <Option name="size_map_unit_scale" type="QString" value="3x:0,0,0,0,0,0"/>
            <Option name="size_unit" type="QString" value="MM"/>
            <Option name="vertical_anchor_point" type="QString" value="1"/>
          </Option>
          <data_defined_properties>
            <Option type="Map">
              <Option name="name" type="QString" value=""/>
              <Option name="properties" type="Map">
                <Option name="fillColor" type="Map">
                  <Option name="active" type="bool" value="true"/>
                  <Option name="expression" type="QString" value="array_get(array('#1f77b4', '#ff7f0e', '#9467bd', '#e377c2', '#17becf', '#8c564b', '#393b79', '#bcbd22', '#00796b', '#c51b7d'), (coalesce(&quot;asema_nro&quot;, 1) - 1) % 10)"/>
                  <Option name="type" type="int" value="3"/>
                </Option>
              </Option>
              <Option name="type" type="QString" value="collection"/>
            </Option>
          </data_defined_properties>
        </layer>
        <layer class="SimpleMarker" enabled="1" id="{ff3706dd-f07b-4281-b739-ea4e5eb5d537}" locked="0" pass="0">
          <Option type="Map">
            <Option name="angle" type="QString" value="0"/>
            <Option name="cap_style" type="QString" value="square"/>
            <Option name="color" type="QString" value="165,0,38,255,rgb:0.6470588,0,0.1490196,1"/>
            <Option name="horizontal_anchor_point" type="QString" value="1"/>
            <Option name="joinstyle" type="QString" value="bevel"/>
            <Option name="name" type="QString" value="triangle"/>
            <Option name="offset" type="QString" value="0,0"/>
            <Option name="offset_map_unit_scale" type="QString" value="3x:0,0,0,0,0,0"/>
            <Option name="offset_unit" type="QString" value="MM"/>
            <Option name="outline_color" type="QString" value="35,35,35,255,rgb:0.1372549,0.1372549,0.1372549,1"/>
            <Option name="outline_style" type="QString" value="solid"/>
            <Option name="outline_width" type="QString" value="0.3"/>
            <Option name="outline_width_map_unit_scale" type="QString" value="3x:0,0,0,0,0,0"/>
            <Option name="outline_width_unit" type="QString" value="MM"/>
            <Option name="scale_method" type="QString" value="diameter"/>
            <Option name="size" type="QString" value="4.2"/>
            <Option name="size_map_unit_scale" type="QString" value="3x:0,0,0,0,0,0"/>
            <Option name="size_unit" type="QString" value="MM"/>
            <Option name="vertical_anchor_point" type="QString" value="1"/>
          </Option>
          <data_defined_properties>
            <Option type="Map">
              <Option name="name" type="QString" value=""/>
              <Option name="properties"/>
              <Option name="type" type="QString" value="collection"/>
            </Option>
          </data_defined_properties>
        </layer>
      </symbol>
      <symbol alpha="1" clip_to_extent="1" force_rhr="0" frame_rate="10" is_animated="0" name="5" type="marker">
        <data_defined_properties>
          <Option type="Map">
            <Option name="name" type="QString" value=""/>
            <Option name="properties"/>
            <Option name="type" type="QString" value="collection"/>
          </Option>
        </data_defined_properties>
        <layer class="SimpleMarker" enabled="1" id="{76b6edca-72b4-4653-b36b-15f9df3c10eb}" locked="0" pass="0">
          <Option type="Map">
            <Option name="angle" type="QString" value="0"/>
            <Option name="cap_style" type="QString" value="square"/>
            <Option name="color" type="QString" value="0,0,0,255,rgb:0,0,0,1"/>
            <Option name="horizontal_anchor_point" type="QString" value="1"/>
            <Option name="joinstyle" type="QString" value="bevel"/>
            <Option name="name" type="QString" value="triangle"/>
            <Option name="offset" type="QString" value="0,0"/>
            <Option name="offset_map_unit_scale" type="QString" value="3x:0,0,0,0,0,0"/>
            <Option name="offset_unit" type="QString" value="MM"/>
            <Option name="outline_color" type="QString" value="35,35,35,255,rgb:0.1372549,0.1372549,0.1372549,1"/>
            <Option name="outline_style" type="QString" value="solid"/>
            <Option name="outline_width" type="QString" value="0.3"/>
            <Option name="outline_width_map_unit_scale" type="QString" value="3x:0,0,0,0,0,0"/>
            <Option name="outline_width_unit" type="QString" value="MM"/>
            <Option name="scale_method" type="QString" value="diameter"/>
            <Option name="size" type="QString" value="7.5"/>
            <Option name="size_map_unit_scale" type="QString" value="3x:0,0,0,0,0,0"/>
            <Option name="size_unit" type="QString" value="MM"/>
            <Option name="vertical_anchor_point" type="QString" value="1"/>
          </Option>
          <data_defined_properties>
            <Option type="Map">
              <Option name="name" type="QString" value=""/>
              <Option name="properties" type="Map">
                <Option name="fillColor" type="Map">
                  <Option name="active" type="bool" value="true"/>
                  <Option name="expression" type="QString" value="array_get(array('#1f77b4', '#ff7f0e', '#9467bd', '#e377c2', '#17becf', '#8c564b', '#393b79', '#bcbd22', '#00796b', '#c51b7d'), (coalesce(&quot;asema_nro&quot;, 1) - 1) % 10)"/>
                  <Option name="type" type="int" value="3"/>
                </Option>
              </Option>
              <Option name="type" type="QString" value="collection"/>
            </Option>
          </data_defined_properties>
        </layer>
        <layer class="SimpleMarker" enabled="1" id="{434a3ad5-d99d-4cef-8d85-9c4502e6a22e}" locked="0" pass="0">
          <Option type="Map">
            <Option name="angle" type="QString" value="0"/>
            <Option name="cap_style" type="QString" value="square"/>
            <Option name="color" type="QString" value="150,150,150,255,rgb:0.5882353,0.5882353,0.5882353,1"/>
            <Option name="horizontal_anchor_point" type="QString" value="1"/>
            <Option name="joinstyle" type="QString" value="bevel"/>
            <Option name="name" type="QString" value="triangle"/>
            <Option name="offset" type="QString" value="0,0"/>
            <Option name="offset_map_unit_scale" type="QString" value="3x:0,0,0,0,0,0"/>
            <Option name="offset_unit" type="QString" value="MM"/>
            <Option name="outline_color" type="QString" value="35,35,35,255,rgb:0.1372549,0.1372549,0.1372549,1"/>
            <Option name="outline_style" type="QString" value="solid"/>
            <Option name="outline_width" type="QString" value="0.3"/>
            <Option name="outline_width_map_unit_scale" type="QString" value="3x:0,0,0,0,0,0"/>
            <Option name="outline_width_unit" type="QString" value="MM"/>
            <Option name="scale_method" type="QString" value="diameter"/>
            <Option name="size" type="QString" value="4.2"/>
            <Option name="size_map_unit_scale" type="QString" value="3x:0,0,0,0,0,0"/>
            <Option name="size_unit" type="QString" value="MM"/>
            <Option name="vertical_anchor_point" type="QString" value="1"/>
          </Option>
          <data_defined_properties>
            <Option type="Map">
              <Option name="name" type="QString" value=""/>
              <Option name="properties"/>
              <Option name="type" type="QString" value="collection"/>
            </Option>
          </data_defined_properties>
        </layer>
      </symbol>
    </symbols>
    <rotation/>
    <sizescale/>
    <data-defined-properties>
      <Option type="Map">
        <Option name="name" type="QString" value=""/>
        <Option name="properties"/>
        <Option name="type" type="QString" value="collection"/>
      </Option>
    </data-defined-properties>
  </renderer-v2>
  <selection mode="Default">
    <selectionColor invalid="1"/>
  </selection>
  <labeling type="simple">
    <settings calloutType="simple">
      <text-style allowHtml="0" blendMode="0" capitalization="0" fieldName="&quot;asema&quot;" fontFamily="Arial" fontItalic="0" fontKerning="1" fontLetterSpacing="0" fontSize="9" fontSizeMapUnitScale="3x:0,0,0,0,0,0" fontSizeUnit="Point" fontStrikeout="0" fontUnderline="0" fontWeight="400" fontWordSpacing="0" forcedBold="0" forcedItalic="0" isExpression="1" legendString="Aa" multilineHeight="1" multilineHeightUnit="Percentage" namedStyle="" previewBkgrdColor="255,255,255,255,rgb:1,1,1,1" tabStopDistance="6" tabStopDistanceMapUnitScale="3x:0,0,0,0,0,0" tabStopDistanceUnit="Percentage" textColor="0,0,0,255,rgb:0,0,0,1" textOpacity="1" textOrientation="horizontal" useSubstitutions="0">
        <families/>
        <text-buffer bufferBlendMode="0" bufferColor="255,255,255,255,rgb:1,1,1,1" bufferDraw="1" bufferJoinStyle="128" bufferNoFill="1" bufferOpacity="1" bufferSize="1" bufferSizeMapUnitScale="3x:0,0,0,0,0,0" bufferSizeUnits="MM"/>
        <text-mask maskEnabled="0" maskJoinStyle="128" maskOpacity="1" maskSize="1.5" maskSize2="1.5" maskSizeMapUnitScale="3x:0,0,0,0,0,0" maskSizeUnits="MM" maskType="0" maskedSymbolLayers=""/>
        <background shapeBlendMode="0" shapeBorderColor="128,128,128,255,rgb:0.5019608,0.5019608,0.5019608,1" shapeBorderWidth="0" shapeBorderWidthMapUnitScale="3x:0,0,0,0,0,0" shapeBorderWidthUnit="MM" shapeDraw="0" shapeFillColor="255,255,255,255,rgb:1,1,1,1" shapeJoinStyle="64" shapeOffsetMapUnitScale="3x:0,0,0,0,0,0" shapeOffsetUnit="MM" shapeOffsetX="0" shapeOffsetY="0" shapeOpacity="1" shapeRadiiMapUnitScale="3x:0,0,0,0,0,0" shapeRadiiUnit="MM" shapeRadiiX="0" shapeRadiiY="0" shapeRotation="0" shapeRotationType="0" shapeSVGFile="" shapeSizeMapUnitScale="3x:0,0,0,0,0,0" shapeSizeType="0" shapeSizeUnit="MM" shapeSizeX="0" shapeSizeY="0" shapeType="0">
          <symbol alpha="1" clip_to_extent="1" force_rhr="0" frame_rate="10" is_animated="0" name="fillSymbol" type="fill">
            <data_defined_properties>
              <Option type="Map">
                <Option name="name" type="QString" value=""/>
                <Option name="properties"/>
                <Option name="type" type="QString" value="collection"/>
              </Option>
            </data_defined_properties>
            <layer class="SimpleFill" enabled="1" id="" locked="0" pass="0">
              <Option type="Map">
                <Option name="border_width_map_unit_scale" type="QString" value="3x:0,0,0,0,0,0"/>
                <Option name="color" type="QString" value="255,255,255,255,rgb:1,1,1,1"/>
                <Option name="joinstyle" type="QString" value="bevel"/>
                <Option name="offset" type="QString" value="0,0"/>
                <Option name="offset_map_unit_scale" type="QString" value="3x:0,0,0,0,0,0"/>
                <Option name="offset_unit" type="QString" value="MM"/>
                <Option name="outline_color" type="QString" value="128,128,128,255,rgb:0.5019608,0.5019608,0.5019608,1"/>
                <Option name="outline_style" type="QString" value="no"/>
                <Option name="outline_width" type="QString" value="0"/>
                <Option name="outline_width_unit" type="QString" value="MM"/>
                <Option name="style" type="QString" value="solid"/>
              </Option>
              <data_defined_properties>
                <Option type="Map">
                  <Option name="name" type="QString" value=""/>
                  <Option name="properties"/>
                  <Option name="type" type="QString" value="collection"/>
                </Option>
              </data_defined_properties>
            </layer>
          </symbol>
        </background>
        <shadow shadowBlendMode="6" shadowColor="0,0,0,255,rgb:0,0,0,1" shadowDraw="0" shadowOffsetAngle="135" shadowOffsetDist="1" shadowOffsetGlobal="1" shadowOffsetMapUnitScale="3x:0,0,0,0,0,0" shadowOffsetUnit="MM" shadowOpacity="0.69999999999999996" shadowRadius="1.5" shadowRadiusAlphaOnly="0" shadowRadiusMapUnitScale="3x:0,0,0,0,0,0" shadowRadiusUnit="MM" shadowScale="100" shadowUnder="0"/>
        <dd_properties>
          <Option type="Map">
            <Option name="name" type="QString" value=""/>
            <Option name="properties"/>
            <Option name="type" type="QString" value="collection"/>
          </Option>
        </dd_properties>
        <substitutions/>
      </text-style>
      <text-format addDirectionSymbol="0" autoWrapLength="0" decimals="3" formatNumbers="0" leftDirectionSymbol="&lt;" multilineAlign="3" placeDirectionSymbol="0" plussign="0" reverseDirectionSymbol="0" rightDirectionSymbol=">" useMaxLineLengthForAutoWrap="1" wrapChar=""/>
      <placement allowDegraded="0" centroidInside="0" centroidWhole="0" dist="1.5" distMapUnitScale="3x:0,0,0,0,0,0" distUnits="MM" fitInPolygonOnly="0" geometryGenerator="" geometryGeneratorEnabled="0" geometryGeneratorType="PointGeometry" labelOffsetMapUnitScale="3x:0,0,0,0,0,0" layerType="UnknownGeometry" lineAnchorClipping="0" lineAnchorPercent="0.5" lineAnchorTextPoint="FollowPlacement" lineAnchorType="0" maxCurvedCharAngleIn="25" maxCurvedCharAngleOut="-25" maximumDistance="0" maximumDistanceMapUnitScale="3x:0,0,0,0,0,0" maximumDistanceUnit="MM" multipartBehavior="LabelLargestPartOnly" offsetType="0" offsetUnits="MM" overlapHandling="PreventOverlap" overrunDistance="0" overrunDistanceMapUnitScale="3x:0,0,0,0,0,0" overrunDistanceUnit="MM" placement="0" placementFlags="10" polygonPlacementFlags="2" predefinedPositionOrder="TR,TL,BR,BL,R,L,TSR,BSR" preserveRotation="1" prioritization="PreferCloser" priority="5" quadOffset="4" repeatDistance="0" repeatDistanceMapUnitScale="3x:0,0,0,0,0,0" repeatDistanceUnits="MM" rotationAngle="0" rotationUnit="AngleDegrees" xOffset="0" yOffset="0"/>
      <rendering drawLabels="1" fontLimitPixelSize="0" fontMaxPixelSize="10000" fontMinPixelSize="0" limitNumLabels="0" maxNumLabels="2000" mergeLines="0" minFeatureSize="0" obstacle="1" obstacleFactor="1" obstacleType="1" scaleMax="0" scaleMin="0" scaleVisibility="0" unplacedVisibility="0" upsidedownLabels="0" zIndex="0"/>
      <dd_properties>
        <Option type="Map">
          <Option name="name" type="QString" value=""/>
          <Option name="properties"/>
          <Option name="type" type="QString" value="collection"/>
        </Option>
      </dd_properties>
      <callout type="simple">
        <Option type="Map">
          <Option name="anchorPoint" type="QString" value="pole_of_inaccessibility"/>
          <Option name="blendMode" type="int" value="0"/>
          <Option name="ddProperties" type="Map">
            <Option name="name" type="QString" value=""/>
            <Option name="properties"/>
            <Option name="type" type="QString" value="collection"/>
          </Option>
          <Option name="drawToAllParts" type="bool" value="false"/>
          <Option name="enabled" type="QString" value="0"/>
          <Option name="labelAnchorPoint" type="QString" value="point_on_exterior"/>
          <Option name="lineSymbol" type="QString" value="&lt;symbol alpha=&quot;1&quot; clip_to_extent=&quot;1&quot; force_rhr=&quot;0&quot; frame_rate=&quot;10&quot; is_animated=&quot;0&quot; name=&quot;symbol&quot; type=&quot;line&quot;>&lt;data_defined_properties>&lt;Option type=&quot;Map&quot;>&lt;Option name=&quot;name&quot; type=&quot;QString&quot; value=&quot;&quot;/>&lt;Option name=&quot;properties&quot;/>&lt;Option name=&quot;type&quot; type=&quot;QString&quot; value=&quot;collection&quot;/>&lt;/Option>&lt;/data_defined_properties>&lt;layer class=&quot;SimpleLine&quot; enabled=&quot;1&quot; id=&quot;{dcb22470-964d-4046-bc8d-06e428b442af}&quot; locked=&quot;0&quot; pass=&quot;0&quot;>&lt;Option type=&quot;Map&quot;>&lt;Option name=&quot;align_dash_pattern&quot; type=&quot;QString&quot; value=&quot;0&quot;/>&lt;Option name=&quot;capstyle&quot; type=&quot;QString&quot; value=&quot;square&quot;/>&lt;Option name=&quot;customdash&quot; type=&quot;QString&quot; value=&quot;5;2&quot;/>&lt;Option name=&quot;customdash_map_unit_scale&quot; type=&quot;QString&quot; value=&quot;3x:0,0,0,0,0,0&quot;/>&lt;Option name=&quot;customdash_unit&quot; type=&quot;QString&quot; value=&quot;MM&quot;/>&lt;Option name=&quot;dash_pattern_offset&quot; type=&quot;QString&quot; value=&quot;0&quot;/>&lt;Option name=&quot;dash_pattern_offset_map_unit_scale&quot; type=&quot;QString&quot; value=&quot;3x:0,0,0,0,0,0&quot;/>&lt;Option name=&quot;dash_pattern_offset_unit&quot; type=&quot;QString&quot; value=&quot;MM&quot;/>&lt;Option name=&quot;draw_inside_polygon&quot; type=&quot;QString&quot; value=&quot;0&quot;/>&lt;Option name=&quot;joinstyle&quot; type=&quot;QString&quot; value=&quot;bevel&quot;/>&lt;Option name=&quot;line_color&quot; type=&quot;QString&quot; value=&quot;60,60,60,255,rgb:0.2352941,0.2352941,0.2352941,1&quot;/>&lt;Option name=&quot;line_style&quot; type=&quot;QString&quot; value=&quot;solid&quot;/>&lt;Option name=&quot;line_width&quot; type=&quot;QString&quot; value=&quot;0.3&quot;/>&lt;Option name=&quot;line_width_unit&quot; type=&quot;QString&quot; value=&quot;MM&quot;/>&lt;Option name=&quot;offset&quot; type=&quot;QString&quot; value=&quot;0&quot;/>&lt;Option name=&quot;offset_map_unit_scale&quot; type=&quot;QString&quot; value=&quot;3x:0,0,0,0,0,0&quot;/>&lt;Option name=&quot;offset_unit&quot; type=&quot;QString&quot; value=&quot;MM&quot;/>&lt;Option name=&quot;ring_filter&quot; type=&quot;QString&quot; value=&quot;0&quot;/>&lt;Option name=&quot;trim_distance_end&quot; type=&quot;QString&quot; value=&quot;0&quot;/>&lt;Option name=&quot;trim_distance_end_map_unit_scale&quot; type=&quot;QString&quot; value=&quot;3x:0,0,0,0,0,0&quot;/>&lt;Option name=&quot;trim_distance_end_unit&quot; type=&quot;QString&quot; value=&quot;MM&quot;/>&lt;Option name=&quot;trim_distance_start&quot; type=&quot;QString&quot; value=&quot;0&quot;/>&lt;Option name=&quot;trim_distance_start_map_unit_scale&quot; type=&quot;QString&quot; value=&quot;3x:0,0,0,0,0,0&quot;/>&lt;Option name=&quot;trim_distance_start_unit&quot; type=&quot;QString&quot; value=&quot;MM&quot;/>&lt;Option name=&quot;tweak_dash_pattern_on_corners&quot; type=&quot;QString&quot; value=&quot;0&quot;/>&lt;Option name=&quot;use_custom_dash&quot; type=&quot;QString&quot; value=&quot;0&quot;/>&lt;Option name=&quot;width_map_unit_scale&quot; type=&quot;QString&quot; value=&quot;3x:0,0,0,0,0,0&quot;/>&lt;/Option>&lt;data_defined_properties>&lt;Option type=&quot;Map&quot;>&lt;Option name=&quot;name&quot; type=&quot;QString&quot; value=&quot;&quot;/>&lt;Option name=&quot;properties&quot;/>&lt;Option name=&quot;type&quot; type=&quot;QString&quot; value=&quot;collection&quot;/>&lt;/Option>&lt;/data_defined_properties>&lt;/layer>&lt;/symbol>"/>
          <Option name="minLength" type="double" value="0"/>
          <Option name="minLengthMapUnitScale" type="QString" value="3x:0,0,0,0,0,0"/>
          <Option name="minLengthUnit" type="QString" value="MM"/>
          <Option name="offsetFromAnchor" type="double" value="0"/>
          <Option name="offsetFromAnchorMapUnitScale" type="QString" value="3x:0,0,0,0,0,0"/>
          <Option name="offsetFromAnchorUnit" type="QString" value="MM"/>
          <Option name="offsetFromLabel" type="double" value="0"/>
          <Option name="offsetFromLabelMapUnitScale" type="QString" value="3x:0,0,0,0,0,0"/>
          <Option name="offsetFromLabelUnit" type="QString" value="MM"/>
        </Option>
      </callout>
    </settings>
  </labeling>
  <blendMode>0</blendMode>
  <featureBlendMode>0</featureBlendMode>
  <layerGeometryType>0</layerGeometryType>
</qgis>
$qml$),
        true, 'Tietokanta-repon oletustyyli');

UPDATE public.layer_styles SET useasdefault = false
    WHERE f_table_schema = 'public' AND f_table_name = 'asemien_liitokset';
DELETE FROM public.layer_styles
    WHERE f_table_schema = 'public' AND f_table_name = 'asemien_liitokset' AND stylename = 'Tietokanta';
INSERT INTO public.layer_styles
    (f_table_catalog, f_table_schema, f_table_name, f_geometry_column, stylename, styleqml, useasdefault,
     description)
VALUES (current_database(), 'public', 'asemien_liitokset', 'geom', 'Tietokanta', XMLPARSE(DOCUMENT $qml$<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis labelsEnabled="1" layerType="Vector" styleCategories="Symbology|Labeling" version="4.2.1-Belém do Pará">
  <renderer-v2 enableorderby="0" forceraster="0" referencescale="-1" symbollevels="0" type="singleSymbol">
    <symbols>
      <symbol alpha="1" clip_to_extent="1" force_rhr="0" frame_rate="10" is_animated="0" name="0" type="line">
        <data_defined_properties>
          <Option type="Map">
            <Option name="name" type="QString" value=""/>
            <Option name="properties"/>
            <Option name="type" type="QString" value="collection"/>
          </Option>
        </data_defined_properties>
        <layer class="SimpleLine" enabled="1" id="{df5c255c-f3fe-401a-b1e3-6a27a684dea6}" locked="0" pass="0">
          <Option type="Map">
            <Option name="align_dash_pattern" type="QString" value="0"/>
            <Option name="capstyle" type="QString" value="square"/>
            <Option name="customdash" type="QString" value="5;2"/>
            <Option name="customdash_map_unit_scale" type="QString" value="3x:0,0,0,0,0,0"/>
            <Option name="customdash_unit" type="QString" value="MM"/>
            <Option name="dash_pattern_offset" type="QString" value="0"/>
            <Option name="dash_pattern_offset_map_unit_scale" type="QString" value="3x:0,0,0,0,0,0"/>
            <Option name="dash_pattern_offset_unit" type="QString" value="MM"/>
            <Option name="draw_inside_polygon" type="QString" value="0"/>
            <Option name="joinstyle" type="QString" value="bevel"/>
            <Option name="line_color" type="QString" value="0,0,0,255,rgb:0,0,0,1"/>
            <Option name="line_style" type="QString" value="solid"/>
            <Option name="line_width" type="QString" value="0.6"/>
            <Option name="line_width_unit" type="QString" value="MM"/>
            <Option name="offset" type="QString" value="0"/>
            <Option name="offset_map_unit_scale" type="QString" value="3x:0,0,0,0,0,0"/>
            <Option name="offset_unit" type="QString" value="MM"/>
            <Option name="ring_filter" type="QString" value="0"/>
            <Option name="trim_distance_end" type="QString" value="0"/>
            <Option name="trim_distance_end_map_unit_scale" type="QString" value="3x:0,0,0,0,0,0"/>
            <Option name="trim_distance_end_unit" type="QString" value="MM"/>
            <Option name="trim_distance_start" type="QString" value="0"/>
            <Option name="trim_distance_start_map_unit_scale" type="QString" value="3x:0,0,0,0,0,0"/>
            <Option name="trim_distance_start_unit" type="QString" value="MM"/>
            <Option name="tweak_dash_pattern_on_corners" type="QString" value="0"/>
            <Option name="use_custom_dash" type="QString" value="0"/>
            <Option name="width_map_unit_scale" type="QString" value="3x:0,0,0,0,0,0"/>
          </Option>
          <data_defined_properties>
            <Option type="Map">
              <Option name="name" type="QString" value=""/>
              <Option name="properties" type="Map">
                <Option name="outlineColor" type="Map">
                  <Option name="active" type="bool" value="true"/>
                  <Option name="expression" type="QString" value="array_get(array('#1f77b4', '#ff7f0e', '#9467bd', '#e377c2', '#17becf', '#8c564b', '#393b79', '#bcbd22', '#00796b', '#c51b7d'), (coalesce(&quot;asema_nro&quot;, 1) - 1) % 10)"/>
                  <Option name="type" type="int" value="3"/>
                </Option>
                <Option name="outlineStyle" type="Map">
                  <Option name="active" type="bool" value="true"/>
                  <Option name="expression" type="QString" value="if(&quot;tyyppi&quot; = 'korkeusliitos', 'dash', 'solid')"/>
                  <Option name="type" type="int" value="3"/>
                </Option>
              </Option>
              <Option name="type" type="QString" value="collection"/>
            </Option>
          </data_defined_properties>
        </layer>
      </symbol>
    </symbols>
    <rotation/>
    <sizescale/>
    <data-defined-properties>
      <Option type="Map">
        <Option name="name" type="QString" value=""/>
        <Option name="properties"/>
        <Option name="type" type="QString" value="collection"/>
      </Option>
    </data-defined-properties>
  </renderer-v2>
  <selection mode="Default">
    <selectionColor invalid="1"/>
  </selection>
  <labeling type="simple">
    <settings calloutType="simple">
      <text-style allowHtml="0" blendMode="0" capitalization="0" fieldName="&quot;liitospiste&quot; || coalesce(' ' || format_number(&quot;dhz_mm&quot;, 1) || ' mm', '')" fontFamily="Arial" fontItalic="0" fontKerning="1" fontLetterSpacing="0" fontSize="8" fontSizeMapUnitScale="3x:0,0,0,0,0,0" fontSizeUnit="Point" fontStrikeout="0" fontUnderline="0" fontWeight="400" fontWordSpacing="0" forcedBold="0" forcedItalic="0" isExpression="1" legendString="Aa" multilineHeight="1" multilineHeightUnit="Percentage" namedStyle="" previewBkgrdColor="255,255,255,255,rgb:1,1,1,1" tabStopDistance="6" tabStopDistanceMapUnitScale="3x:0,0,0,0,0,0" tabStopDistanceUnit="Percentage" textColor="0,0,0,255,rgb:0,0,0,1" textOpacity="1" textOrientation="horizontal" useSubstitutions="0">
        <families/>
        <text-buffer bufferBlendMode="0" bufferColor="255,255,255,255,rgb:1,1,1,1" bufferDraw="1" bufferJoinStyle="128" bufferNoFill="1" bufferOpacity="1" bufferSize="1" bufferSizeMapUnitScale="3x:0,0,0,0,0,0" bufferSizeUnits="MM"/>
        <text-mask maskEnabled="0" maskJoinStyle="128" maskOpacity="1" maskSize="1.5" maskSize2="1.5" maskSizeMapUnitScale="3x:0,0,0,0,0,0" maskSizeUnits="MM" maskType="0" maskedSymbolLayers=""/>
        <background shapeBlendMode="0" shapeBorderColor="128,128,128,255,rgb:0.5019608,0.5019608,0.5019608,1" shapeBorderWidth="0" shapeBorderWidthMapUnitScale="3x:0,0,0,0,0,0" shapeBorderWidthUnit="MM" shapeDraw="0" shapeFillColor="255,255,255,255,rgb:1,1,1,1" shapeJoinStyle="64" shapeOffsetMapUnitScale="3x:0,0,0,0,0,0" shapeOffsetUnit="MM" shapeOffsetX="0" shapeOffsetY="0" shapeOpacity="1" shapeRadiiMapUnitScale="3x:0,0,0,0,0,0" shapeRadiiUnit="MM" shapeRadiiX="0" shapeRadiiY="0" shapeRotation="0" shapeRotationType="0" shapeSVGFile="" shapeSizeMapUnitScale="3x:0,0,0,0,0,0" shapeSizeType="0" shapeSizeUnit="MM" shapeSizeX="0" shapeSizeY="0" shapeType="0">
          <symbol alpha="1" clip_to_extent="1" force_rhr="0" frame_rate="10" is_animated="0" name="fillSymbol" type="fill">
            <data_defined_properties>
              <Option type="Map">
                <Option name="name" type="QString" value=""/>
                <Option name="properties"/>
                <Option name="type" type="QString" value="collection"/>
              </Option>
            </data_defined_properties>
            <layer class="SimpleFill" enabled="1" id="" locked="0" pass="0">
              <Option type="Map">
                <Option name="border_width_map_unit_scale" type="QString" value="3x:0,0,0,0,0,0"/>
                <Option name="color" type="QString" value="255,255,255,255,rgb:1,1,1,1"/>
                <Option name="joinstyle" type="QString" value="bevel"/>
                <Option name="offset" type="QString" value="0,0"/>
                <Option name="offset_map_unit_scale" type="QString" value="3x:0,0,0,0,0,0"/>
                <Option name="offset_unit" type="QString" value="MM"/>
                <Option name="outline_color" type="QString" value="128,128,128,255,rgb:0.5019608,0.5019608,0.5019608,1"/>
                <Option name="outline_style" type="QString" value="no"/>
                <Option name="outline_width" type="QString" value="0"/>
                <Option name="outline_width_unit" type="QString" value="MM"/>
                <Option name="style" type="QString" value="solid"/>
              </Option>
              <data_defined_properties>
                <Option type="Map">
                  <Option name="name" type="QString" value=""/>
                  <Option name="properties"/>
                  <Option name="type" type="QString" value="collection"/>
                </Option>
              </data_defined_properties>
            </layer>
          </symbol>
        </background>
        <shadow shadowBlendMode="6" shadowColor="0,0,0,255,rgb:0,0,0,1" shadowDraw="0" shadowOffsetAngle="135" shadowOffsetDist="1" shadowOffsetGlobal="1" shadowOffsetMapUnitScale="3x:0,0,0,0,0,0" shadowOffsetUnit="MM" shadowOpacity="0.69999999999999996" shadowRadius="1.5" shadowRadiusAlphaOnly="0" shadowRadiusMapUnitScale="3x:0,0,0,0,0,0" shadowRadiusUnit="MM" shadowScale="100" shadowUnder="0"/>
        <dd_properties>
          <Option type="Map">
            <Option name="name" type="QString" value=""/>
            <Option name="properties"/>
            <Option name="type" type="QString" value="collection"/>
          </Option>
        </dd_properties>
        <substitutions/>
      </text-style>
      <text-format addDirectionSymbol="0" autoWrapLength="0" decimals="3" formatNumbers="0" leftDirectionSymbol="&lt;" multilineAlign="3" placeDirectionSymbol="0" plussign="0" reverseDirectionSymbol="0" rightDirectionSymbol=">" useMaxLineLengthForAutoWrap="1" wrapChar=""/>
      <placement allowDegraded="0" centroidInside="0" centroidWhole="0" dist="1.5" distMapUnitScale="3x:0,0,0,0,0,0" distUnits="MM" fitInPolygonOnly="0" geometryGenerator="" geometryGeneratorEnabled="0" geometryGeneratorType="PointGeometry" labelOffsetMapUnitScale="3x:0,0,0,0,0,0" layerType="UnknownGeometry" lineAnchorClipping="0" lineAnchorPercent="0.5" lineAnchorTextPoint="FollowPlacement" lineAnchorType="0" maxCurvedCharAngleIn="25" maxCurvedCharAngleOut="-25" maximumDistance="0" maximumDistanceMapUnitScale="3x:0,0,0,0,0,0" maximumDistanceUnit="MM" multipartBehavior="LabelLargestPartOnly" offsetType="0" offsetUnits="MM" overlapHandling="PreventOverlap" overrunDistance="0" overrunDistanceMapUnitScale="3x:0,0,0,0,0,0" overrunDistanceUnit="MM" placement="2" placementFlags="10" polygonPlacementFlags="2" predefinedPositionOrder="TR,TL,BR,BL,R,L,TSR,BSR" preserveRotation="1" prioritization="PreferCloser" priority="5" quadOffset="4" repeatDistance="0" repeatDistanceMapUnitScale="3x:0,0,0,0,0,0" repeatDistanceUnits="MM" rotationAngle="0" rotationUnit="AngleDegrees" xOffset="0" yOffset="0"/>
      <rendering drawLabels="1" fontLimitPixelSize="0" fontMaxPixelSize="10000" fontMinPixelSize="0" limitNumLabels="0" maxNumLabels="2000" mergeLines="0" minFeatureSize="0" obstacle="1" obstacleFactor="1" obstacleType="1" scaleMax="0" scaleMin="0" scaleVisibility="0" unplacedVisibility="0" upsidedownLabels="0" zIndex="0"/>
      <dd_properties>
        <Option type="Map">
          <Option name="name" type="QString" value=""/>
          <Option name="properties" type="Map">
            <Option name="Color" type="Map">
              <Option name="active" type="bool" value="true"/>
              <Option name="expression" type="QString" value="if(&quot;dhz_mm&quot; >= 20, '215,25,28,255', '0,0,0,255')"/>
              <Option name="type" type="int" value="3"/>
            </Option>
          </Option>
          <Option name="type" type="QString" value="collection"/>
        </Option>
      </dd_properties>
      <callout type="simple">
        <Option type="Map">
          <Option name="anchorPoint" type="QString" value="pole_of_inaccessibility"/>
          <Option name="blendMode" type="int" value="0"/>
          <Option name="ddProperties" type="Map">
            <Option name="name" type="QString" value=""/>
            <Option name="properties"/>
            <Option name="type" type="QString" value="collection"/>
          </Option>
          <Option name="drawToAllParts" type="bool" value="false"/>
          <Option name="enabled" type="QString" value="0"/>
          <Option name="labelAnchorPoint" type="QString" value="point_on_exterior"/>
          <Option name="lineSymbol" type="QString" value="&lt;symbol alpha=&quot;1&quot; clip_to_extent=&quot;1&quot; force_rhr=&quot;0&quot; frame_rate=&quot;10&quot; is_animated=&quot;0&quot; name=&quot;symbol&quot; type=&quot;line&quot;>&lt;data_defined_properties>&lt;Option type=&quot;Map&quot;>&lt;Option name=&quot;name&quot; type=&quot;QString&quot; value=&quot;&quot;/>&lt;Option name=&quot;properties&quot;/>&lt;Option name=&quot;type&quot; type=&quot;QString&quot; value=&quot;collection&quot;/>&lt;/Option>&lt;/data_defined_properties>&lt;layer class=&quot;SimpleLine&quot; enabled=&quot;1&quot; id=&quot;{6bfb5450-c203-4986-9344-d5e2fed01501}&quot; locked=&quot;0&quot; pass=&quot;0&quot;>&lt;Option type=&quot;Map&quot;>&lt;Option name=&quot;align_dash_pattern&quot; type=&quot;QString&quot; value=&quot;0&quot;/>&lt;Option name=&quot;capstyle&quot; type=&quot;QString&quot; value=&quot;square&quot;/>&lt;Option name=&quot;customdash&quot; type=&quot;QString&quot; value=&quot;5;2&quot;/>&lt;Option name=&quot;customdash_map_unit_scale&quot; type=&quot;QString&quot; value=&quot;3x:0,0,0,0,0,0&quot;/>&lt;Option name=&quot;customdash_unit&quot; type=&quot;QString&quot; value=&quot;MM&quot;/>&lt;Option name=&quot;dash_pattern_offset&quot; type=&quot;QString&quot; value=&quot;0&quot;/>&lt;Option name=&quot;dash_pattern_offset_map_unit_scale&quot; type=&quot;QString&quot; value=&quot;3x:0,0,0,0,0,0&quot;/>&lt;Option name=&quot;dash_pattern_offset_unit&quot; type=&quot;QString&quot; value=&quot;MM&quot;/>&lt;Option name=&quot;draw_inside_polygon&quot; type=&quot;QString&quot; value=&quot;0&quot;/>&lt;Option name=&quot;joinstyle&quot; type=&quot;QString&quot; value=&quot;bevel&quot;/>&lt;Option name=&quot;line_color&quot; type=&quot;QString&quot; value=&quot;60,60,60,255,rgb:0.2352941,0.2352941,0.2352941,1&quot;/>&lt;Option name=&quot;line_style&quot; type=&quot;QString&quot; value=&quot;solid&quot;/>&lt;Option name=&quot;line_width&quot; type=&quot;QString&quot; value=&quot;0.3&quot;/>&lt;Option name=&quot;line_width_unit&quot; type=&quot;QString&quot; value=&quot;MM&quot;/>&lt;Option name=&quot;offset&quot; type=&quot;QString&quot; value=&quot;0&quot;/>&lt;Option name=&quot;offset_map_unit_scale&quot; type=&quot;QString&quot; value=&quot;3x:0,0,0,0,0,0&quot;/>&lt;Option name=&quot;offset_unit&quot; type=&quot;QString&quot; value=&quot;MM&quot;/>&lt;Option name=&quot;ring_filter&quot; type=&quot;QString&quot; value=&quot;0&quot;/>&lt;Option name=&quot;trim_distance_end&quot; type=&quot;QString&quot; value=&quot;0&quot;/>&lt;Option name=&quot;trim_distance_end_map_unit_scale&quot; type=&quot;QString&quot; value=&quot;3x:0,0,0,0,0,0&quot;/>&lt;Option name=&quot;trim_distance_end_unit&quot; type=&quot;QString&quot; value=&quot;MM&quot;/>&lt;Option name=&quot;trim_distance_start&quot; type=&quot;QString&quot; value=&quot;0&quot;/>&lt;Option name=&quot;trim_distance_start_map_unit_scale&quot; type=&quot;QString&quot; value=&quot;3x:0,0,0,0,0,0&quot;/>&lt;Option name=&quot;trim_distance_start_unit&quot; type=&quot;QString&quot; value=&quot;MM&quot;/>&lt;Option name=&quot;tweak_dash_pattern_on_corners&quot; type=&quot;QString&quot; value=&quot;0&quot;/>&lt;Option name=&quot;use_custom_dash&quot; type=&quot;QString&quot; value=&quot;0&quot;/>&lt;Option name=&quot;width_map_unit_scale&quot; type=&quot;QString&quot; value=&quot;3x:0,0,0,0,0,0&quot;/>&lt;/Option>&lt;data_defined_properties>&lt;Option type=&quot;Map&quot;>&lt;Option name=&quot;name&quot; type=&quot;QString&quot; value=&quot;&quot;/>&lt;Option name=&quot;properties&quot;/>&lt;Option name=&quot;type&quot; type=&quot;QString&quot; value=&quot;collection&quot;/>&lt;/Option>&lt;/data_defined_properties>&lt;/layer>&lt;/symbol>"/>
          <Option name="minLength" type="double" value="0"/>
          <Option name="minLengthMapUnitScale" type="QString" value="3x:0,0,0,0,0,0"/>
          <Option name="minLengthUnit" type="QString" value="MM"/>
          <Option name="offsetFromAnchor" type="double" value="0"/>
          <Option name="offsetFromAnchorMapUnitScale" type="QString" value="3x:0,0,0,0,0,0"/>
          <Option name="offsetFromAnchorUnit" type="QString" value="MM"/>
          <Option name="offsetFromLabel" type="double" value="0"/>
          <Option name="offsetFromLabelMapUnitScale" type="QString" value="3x:0,0,0,0,0,0"/>
          <Option name="offsetFromLabelUnit" type="QString" value="MM"/>
        </Option>
      </callout>
    </settings>
  </labeling>
  <blendMode>0</blendMode>
  <featureBlendMode>0</featureBlendMode>
  <layerGeometryType>1</layerGeometryType>
</qgis>
$qml$),
        true, 'Tietokanta-repon oletustyyli');

UPDATE public.layer_styles SET useasdefault = false
    WHERE f_table_schema = 'public' AND f_table_name = 'mittausraportit';
DELETE FROM public.layer_styles
    WHERE f_table_schema = 'public' AND f_table_name = 'mittausraportit' AND stylename = 'Tietokanta';
INSERT INTO public.layer_styles
    (f_table_catalog, f_table_schema, f_table_name, f_geometry_column, stylename, styleqml, useasdefault,
     description)
VALUES (current_database(), 'public', 'mittausraportit', 'geom', 'Tietokanta', XMLPARSE(DOCUMENT $qml$<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis labelsEnabled="1" layerType="Vector" styleCategories="Symbology|Labeling" version="4.2.1-Belém do Pará">
  <renderer-v2 enableorderby="0" forceraster="0" referencescale="-1" symbollevels="0" type="singleSymbol">
    <symbols>
      <symbol alpha="1" clip_to_extent="1" force_rhr="0" frame_rate="10" is_animated="0" name="0" type="marker">
        <data_defined_properties>
          <Option type="Map">
            <Option name="name" type="QString" value=""/>
            <Option name="properties"/>
            <Option name="type" type="QString" value="collection"/>
          </Option>
        </data_defined_properties>
        <layer class="SimpleMarker" enabled="1" id="{da8d2722-ac15-4338-8a10-e3e6c91412ee}" locked="0" pass="0">
          <Option type="Map">
            <Option name="angle" type="QString" value="0"/>
            <Option name="cap_style" type="QString" value="square"/>
            <Option name="color" type="QString" value="106,61,154,255,rgb:0.4156863,0.2392157,0.6039216,1"/>
            <Option name="horizontal_anchor_point" type="QString" value="1"/>
            <Option name="joinstyle" type="QString" value="bevel"/>
            <Option name="name" type="QString" value="star"/>
            <Option name="offset" type="QString" value="0,0"/>
            <Option name="offset_map_unit_scale" type="QString" value="3x:0,0,0,0,0,0"/>
            <Option name="offset_unit" type="QString" value="MM"/>
            <Option name="outline_color" type="QString" value="255,255,255,255,rgb:1,1,1,1"/>
            <Option name="outline_style" type="QString" value="solid"/>
            <Option name="outline_width" type="QString" value="0.6"/>
            <Option name="outline_width_map_unit_scale" type="QString" value="3x:0,0,0,0,0,0"/>
            <Option name="outline_width_unit" type="QString" value="MM"/>
            <Option name="scale_method" type="QString" value="diameter"/>
            <Option name="size" type="QString" value="8"/>
            <Option name="size_map_unit_scale" type="QString" value="3x:0,0,0,0,0,0"/>
            <Option name="size_unit" type="QString" value="MM"/>
            <Option name="vertical_anchor_point" type="QString" value="1"/>
          </Option>
          <data_defined_properties>
            <Option type="Map">
              <Option name="name" type="QString" value=""/>
              <Option name="properties"/>
              <Option name="type" type="QString" value="collection"/>
            </Option>
          </data_defined_properties>
        </layer>
      </symbol>
    </symbols>
    <rotation/>
    <sizescale/>
    <data-defined-properties>
      <Option type="Map">
        <Option name="name" type="QString" value=""/>
        <Option name="properties"/>
        <Option name="type" type="QString" value="collection"/>
      </Option>
    </data-defined-properties>
  </renderer-v2>
  <selection mode="Default">
    <selectionColor invalid="1"/>
  </selection>
  <labeling type="simple">
    <settings calloutType="simple">
      <text-style allowHtml="0" blendMode="0" capitalization="0" fieldName="'Raportti: ' || &quot;lahdetiedosto&quot;" fontFamily="Arial" fontItalic="0" fontKerning="1" fontLetterSpacing="0" fontSize="9" fontSizeMapUnitScale="3x:0,0,0,0,0,0" fontSizeUnit="Point" fontStrikeout="0" fontUnderline="0" fontWeight="400" fontWordSpacing="0" forcedBold="0" forcedItalic="0" isExpression="1" legendString="Aa" multilineHeight="1" multilineHeightUnit="Percentage" namedStyle="" previewBkgrdColor="255,255,255,255,rgb:1,1,1,1" tabStopDistance="6" tabStopDistanceMapUnitScale="3x:0,0,0,0,0,0" tabStopDistanceUnit="Percentage" textColor="0,0,0,255,rgb:0,0,0,1" textOpacity="1" textOrientation="horizontal" useSubstitutions="0">
        <families/>
        <text-buffer bufferBlendMode="0" bufferColor="255,255,255,255,rgb:1,1,1,1" bufferDraw="1" bufferJoinStyle="128" bufferNoFill="1" bufferOpacity="1" bufferSize="1" bufferSizeMapUnitScale="3x:0,0,0,0,0,0" bufferSizeUnits="MM"/>
        <text-mask maskEnabled="0" maskJoinStyle="128" maskOpacity="1" maskSize="1.5" maskSize2="1.5" maskSizeMapUnitScale="3x:0,0,0,0,0,0" maskSizeUnits="MM" maskType="0" maskedSymbolLayers=""/>
        <background shapeBlendMode="0" shapeBorderColor="128,128,128,255,rgb:0.5019608,0.5019608,0.5019608,1" shapeBorderWidth="0" shapeBorderWidthMapUnitScale="3x:0,0,0,0,0,0" shapeBorderWidthUnit="MM" shapeDraw="0" shapeFillColor="255,255,255,255,rgb:1,1,1,1" shapeJoinStyle="64" shapeOffsetMapUnitScale="3x:0,0,0,0,0,0" shapeOffsetUnit="MM" shapeOffsetX="0" shapeOffsetY="0" shapeOpacity="1" shapeRadiiMapUnitScale="3x:0,0,0,0,0,0" shapeRadiiUnit="MM" shapeRadiiX="0" shapeRadiiY="0" shapeRotation="0" shapeRotationType="0" shapeSVGFile="" shapeSizeMapUnitScale="3x:0,0,0,0,0,0" shapeSizeType="0" shapeSizeUnit="MM" shapeSizeX="0" shapeSizeY="0" shapeType="0">
          <symbol alpha="1" clip_to_extent="1" force_rhr="0" frame_rate="10" is_animated="0" name="fillSymbol" type="fill">
            <data_defined_properties>
              <Option type="Map">
                <Option name="name" type="QString" value=""/>
                <Option name="properties"/>
                <Option name="type" type="QString" value="collection"/>
              </Option>
            </data_defined_properties>
            <layer class="SimpleFill" enabled="1" id="" locked="0" pass="0">
              <Option type="Map">
                <Option name="border_width_map_unit_scale" type="QString" value="3x:0,0,0,0,0,0"/>
                <Option name="color" type="QString" value="255,255,255,255,rgb:1,1,1,1"/>
                <Option name="joinstyle" type="QString" value="bevel"/>
                <Option name="offset" type="QString" value="0,0"/>
                <Option name="offset_map_unit_scale" type="QString" value="3x:0,0,0,0,0,0"/>
                <Option name="offset_unit" type="QString" value="MM"/>
                <Option name="outline_color" type="QString" value="128,128,128,255,rgb:0.5019608,0.5019608,0.5019608,1"/>
                <Option name="outline_style" type="QString" value="no"/>
                <Option name="outline_width" type="QString" value="0"/>
                <Option name="outline_width_unit" type="QString" value="MM"/>
                <Option name="style" type="QString" value="solid"/>
              </Option>
              <data_defined_properties>
                <Option type="Map">
                  <Option name="name" type="QString" value=""/>
                  <Option name="properties"/>
                  <Option name="type" type="QString" value="collection"/>
                </Option>
              </data_defined_properties>
            </layer>
          </symbol>
        </background>
        <shadow shadowBlendMode="6" shadowColor="0,0,0,255,rgb:0,0,0,1" shadowDraw="0" shadowOffsetAngle="135" shadowOffsetDist="1" shadowOffsetGlobal="1" shadowOffsetMapUnitScale="3x:0,0,0,0,0,0" shadowOffsetUnit="MM" shadowOpacity="0.69999999999999996" shadowRadius="1.5" shadowRadiusAlphaOnly="0" shadowRadiusMapUnitScale="3x:0,0,0,0,0,0" shadowRadiusUnit="MM" shadowScale="100" shadowUnder="0"/>
        <dd_properties>
          <Option type="Map">
            <Option name="name" type="QString" value=""/>
            <Option name="properties"/>
            <Option name="type" type="QString" value="collection"/>
          </Option>
        </dd_properties>
        <substitutions/>
      </text-style>
      <text-format addDirectionSymbol="0" autoWrapLength="0" decimals="3" formatNumbers="0" leftDirectionSymbol="&lt;" multilineAlign="3" placeDirectionSymbol="0" plussign="0" reverseDirectionSymbol="0" rightDirectionSymbol=">" useMaxLineLengthForAutoWrap="1" wrapChar=""/>
      <placement allowDegraded="0" centroidInside="0" centroidWhole="0" dist="1.5" distMapUnitScale="3x:0,0,0,0,0,0" distUnits="MM" fitInPolygonOnly="0" geometryGenerator="" geometryGeneratorEnabled="0" geometryGeneratorType="PointGeometry" labelOffsetMapUnitScale="3x:0,0,0,0,0,0" layerType="UnknownGeometry" lineAnchorClipping="0" lineAnchorPercent="0.5" lineAnchorTextPoint="FollowPlacement" lineAnchorType="0" maxCurvedCharAngleIn="25" maxCurvedCharAngleOut="-25" maximumDistance="0" maximumDistanceMapUnitScale="3x:0,0,0,0,0,0" maximumDistanceUnit="MM" multipartBehavior="LabelLargestPartOnly" offsetType="0" offsetUnits="MM" overlapHandling="PreventOverlap" overrunDistance="0" overrunDistanceMapUnitScale="3x:0,0,0,0,0,0" overrunDistanceUnit="MM" placement="0" placementFlags="10" polygonPlacementFlags="2" predefinedPositionOrder="TR,TL,BR,BL,R,L,TSR,BSR" preserveRotation="1" prioritization="PreferCloser" priority="5" quadOffset="4" repeatDistance="0" repeatDistanceMapUnitScale="3x:0,0,0,0,0,0" repeatDistanceUnits="MM" rotationAngle="0" rotationUnit="AngleDegrees" xOffset="0" yOffset="0"/>
      <rendering drawLabels="1" fontLimitPixelSize="0" fontMaxPixelSize="10000" fontMinPixelSize="0" limitNumLabels="0" maxNumLabels="2000" mergeLines="0" minFeatureSize="0" obstacle="1" obstacleFactor="1" obstacleType="1" scaleMax="0" scaleMin="0" scaleVisibility="0" unplacedVisibility="0" upsidedownLabels="0" zIndex="0"/>
      <dd_properties>
        <Option type="Map">
          <Option name="name" type="QString" value=""/>
          <Option name="properties"/>
          <Option name="type" type="QString" value="collection"/>
        </Option>
      </dd_properties>
      <callout type="simple">
        <Option type="Map">
          <Option name="anchorPoint" type="QString" value="pole_of_inaccessibility"/>
          <Option name="blendMode" type="int" value="0"/>
          <Option name="ddProperties" type="Map">
            <Option name="name" type="QString" value=""/>
            <Option name="properties"/>
            <Option name="type" type="QString" value="collection"/>
          </Option>
          <Option name="drawToAllParts" type="bool" value="false"/>
          <Option name="enabled" type="QString" value="0"/>
          <Option name="labelAnchorPoint" type="QString" value="point_on_exterior"/>
          <Option name="lineSymbol" type="QString" value="&lt;symbol alpha=&quot;1&quot; clip_to_extent=&quot;1&quot; force_rhr=&quot;0&quot; frame_rate=&quot;10&quot; is_animated=&quot;0&quot; name=&quot;symbol&quot; type=&quot;line&quot;>&lt;data_defined_properties>&lt;Option type=&quot;Map&quot;>&lt;Option name=&quot;name&quot; type=&quot;QString&quot; value=&quot;&quot;/>&lt;Option name=&quot;properties&quot;/>&lt;Option name=&quot;type&quot; type=&quot;QString&quot; value=&quot;collection&quot;/>&lt;/Option>&lt;/data_defined_properties>&lt;layer class=&quot;SimpleLine&quot; enabled=&quot;1&quot; id=&quot;{7359008a-a29d-4bed-b743-92a8f5733496}&quot; locked=&quot;0&quot; pass=&quot;0&quot;>&lt;Option type=&quot;Map&quot;>&lt;Option name=&quot;align_dash_pattern&quot; type=&quot;QString&quot; value=&quot;0&quot;/>&lt;Option name=&quot;capstyle&quot; type=&quot;QString&quot; value=&quot;square&quot;/>&lt;Option name=&quot;customdash&quot; type=&quot;QString&quot; value=&quot;5;2&quot;/>&lt;Option name=&quot;customdash_map_unit_scale&quot; type=&quot;QString&quot; value=&quot;3x:0,0,0,0,0,0&quot;/>&lt;Option name=&quot;customdash_unit&quot; type=&quot;QString&quot; value=&quot;MM&quot;/>&lt;Option name=&quot;dash_pattern_offset&quot; type=&quot;QString&quot; value=&quot;0&quot;/>&lt;Option name=&quot;dash_pattern_offset_map_unit_scale&quot; type=&quot;QString&quot; value=&quot;3x:0,0,0,0,0,0&quot;/>&lt;Option name=&quot;dash_pattern_offset_unit&quot; type=&quot;QString&quot; value=&quot;MM&quot;/>&lt;Option name=&quot;draw_inside_polygon&quot; type=&quot;QString&quot; value=&quot;0&quot;/>&lt;Option name=&quot;joinstyle&quot; type=&quot;QString&quot; value=&quot;bevel&quot;/>&lt;Option name=&quot;line_color&quot; type=&quot;QString&quot; value=&quot;60,60,60,255,rgb:0.2352941,0.2352941,0.2352941,1&quot;/>&lt;Option name=&quot;line_style&quot; type=&quot;QString&quot; value=&quot;solid&quot;/>&lt;Option name=&quot;line_width&quot; type=&quot;QString&quot; value=&quot;0.3&quot;/>&lt;Option name=&quot;line_width_unit&quot; type=&quot;QString&quot; value=&quot;MM&quot;/>&lt;Option name=&quot;offset&quot; type=&quot;QString&quot; value=&quot;0&quot;/>&lt;Option name=&quot;offset_map_unit_scale&quot; type=&quot;QString&quot; value=&quot;3x:0,0,0,0,0,0&quot;/>&lt;Option name=&quot;offset_unit&quot; type=&quot;QString&quot; value=&quot;MM&quot;/>&lt;Option name=&quot;ring_filter&quot; type=&quot;QString&quot; value=&quot;0&quot;/>&lt;Option name=&quot;trim_distance_end&quot; type=&quot;QString&quot; value=&quot;0&quot;/>&lt;Option name=&quot;trim_distance_end_map_unit_scale&quot; type=&quot;QString&quot; value=&quot;3x:0,0,0,0,0,0&quot;/>&lt;Option name=&quot;trim_distance_end_unit&quot; type=&quot;QString&quot; value=&quot;MM&quot;/>&lt;Option name=&quot;trim_distance_start&quot; type=&quot;QString&quot; value=&quot;0&quot;/>&lt;Option name=&quot;trim_distance_start_map_unit_scale&quot; type=&quot;QString&quot; value=&quot;3x:0,0,0,0,0,0&quot;/>&lt;Option name=&quot;trim_distance_start_unit&quot; type=&quot;QString&quot; value=&quot;MM&quot;/>&lt;Option name=&quot;tweak_dash_pattern_on_corners&quot; type=&quot;QString&quot; value=&quot;0&quot;/>&lt;Option name=&quot;use_custom_dash&quot; type=&quot;QString&quot; value=&quot;0&quot;/>&lt;Option name=&quot;width_map_unit_scale&quot; type=&quot;QString&quot; value=&quot;3x:0,0,0,0,0,0&quot;/>&lt;/Option>&lt;data_defined_properties>&lt;Option type=&quot;Map&quot;>&lt;Option name=&quot;name&quot; type=&quot;QString&quot; value=&quot;&quot;/>&lt;Option name=&quot;properties&quot;/>&lt;Option name=&quot;type&quot; type=&quot;QString&quot; value=&quot;collection&quot;/>&lt;/Option>&lt;/data_defined_properties>&lt;/layer>&lt;/symbol>"/>
          <Option name="minLength" type="double" value="0"/>
          <Option name="minLengthMapUnitScale" type="QString" value="3x:0,0,0,0,0,0"/>
          <Option name="minLengthUnit" type="QString" value="MM"/>
          <Option name="offsetFromAnchor" type="double" value="0"/>
          <Option name="offsetFromAnchorMapUnitScale" type="QString" value="3x:0,0,0,0,0,0"/>
          <Option name="offsetFromAnchorUnit" type="QString" value="MM"/>
          <Option name="offsetFromLabel" type="double" value="0"/>
          <Option name="offsetFromLabelMapUnitScale" type="QString" value="3x:0,0,0,0,0,0"/>
          <Option name="offsetFromLabelUnit" type="QString" value="MM"/>
        </Option>
      </callout>
    </settings>
  </labeling>
  <blendMode>0</blendMode>
  <featureBlendMode>0</featureBlendMode>
  <layerGeometryType>0</layerGeometryType>
</qgis>
$qml$),
        true, 'Tietokanta-repon oletustyyli');
