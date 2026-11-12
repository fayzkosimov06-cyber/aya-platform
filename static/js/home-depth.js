/* Decorative local meshes: no downloads, tracking, libraries or WebGL requirement. */
(() => {
  'use strict';
  const scene=document.querySelector('[data-depth-scene]'),canvas=scene?.querySelector('[data-aya-model]');
  if(!canvas)return;
  const motion=matchMedia('(prefers-reduced-motion: reduce)'),pointer=matchMedia('(hover: hover) and (pointer: fine)');
  let gl;
  try {gl=canvas.getContext('webgl',{alpha:true,antialias:true,depth:true,powerPreference:'low-power',preserveDrawingBuffer:false});} catch {return;}
  if(!gl)return;
  let program,buffer,vertices,frame=0,visible=false,lost=false,last=0,time=0,rx=0,ry=0;
  const vertex=`attribute vec3 position; attribute vec3 normal;
    uniform mat4 projection; uniform mat4 model; varying vec3 n; varying vec3 p;
    void main(){vec4 point=model*vec4(position,1.0);p=point.xyz;n=mat3(model)*normal;gl_Position=projection*point;}`;
  const fragment=`precision mediump float; varying vec3 n; varying vec3 p; uniform vec3 color;
    void main(){vec3 N=normalize(n);vec3 L=normalize(vec3(-3.0,5.0,7.0));vec3 V=normalize(-p);
      float diffuse=max(dot(N,L),0.0);float edge=pow(1.0-max(dot(N,V),0.0),3.0);
      float shine=pow(max(dot(N,normalize(L+V)),0.0),55.0);
      vec3 surface=color*(0.30+0.70*diffuse)+vec3(0.27,0.47,0.55)*edge+vec3(0.88,0.96,1.0)*shine*0.8;
      gl_FragColor=vec4(surface,1.0);}`;
  function shader(type,source){const s=gl.createShader(type);gl.shaderSource(s,source);gl.compileShader(s);if(!gl.getShaderParameter(s,gl.COMPILE_STATUS)){gl.deleteShader(s);throw Error('shader');}return s;}
  function setup(){
    const a=shader(gl.VERTEX_SHADER,vertex),b=shader(gl.FRAGMENT_SHADER,fragment);
    program=gl.createProgram();gl.attachShader(program,a);gl.attachShader(program,b);gl.linkProgram(program);gl.deleteShader(a);gl.deleteShader(b);
    if(!gl.getProgramParameter(program,gl.LINK_STATUS))throw Error('program');
    gl.useProgram(program);gl.enable(gl.DEPTH_TEST);gl.clearColor(0,0,0,0);
    const data=[],segments=72,tube=20;
    function point(u,v){const a=u*2*Math.PI/segments,b=v*2*Math.PI/tube,c=Math.cos(b),s=Math.sin(b),x=Math.cos(a),y=Math.sin(a);return [(1+.235*c)*x,(1+.235*c)*y,.235*s,c*x,c*y,s];}
    for(let u=0;u<segments;u++)for(let v=0;v<tube;v++){
      const a=point(u,v),b=point(u+1,v),c=point(u+1,v+1),d=point(u,v+1);data.push(...a,...b,...c,...a,...c,...d);
    }
    buffer=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,buffer);gl.bufferData(gl.ARRAY_BUFFER,new Float32Array(data),gl.STATIC_DRAW);vertices=data.length/6;
    for(const [name,offset] of [['position',0],['normal',12]]){const loc=gl.getAttribLocation(program,name);gl.enableVertexAttribArray(loc);gl.vertexAttribPointer(loc,3,gl.FLOAT,false,24,offset);}
  }
  function matrix(ax,ay,az,scale,z){
    const cx=Math.cos(ax),sx=Math.sin(ax),cy=Math.cos(ay),sy=Math.sin(ay),cz=Math.cos(az),sz=Math.sin(az);
    return new Float32Array([cy*cz*scale,(sx*sy*cz+cx*sz)*scale,(-cx*sy*cz+sx*sz)*scale,0,
      -cy*sz*scale,(-sx*sy*sz+cx*cz)*scale,(cx*sy*sz+sx*cz)*scale,0,
      sy*scale,-sx*cy*scale,cx*cy*scale,0,0,.12,z,1]);
  }
  function draw(stamp){
    frame=0;if(lost||!visible||document.hidden)return;
    if(!motion.matches&&stamp-last<33){frame=requestAnimationFrame(draw);return;}
    if(!motion.matches&&last)time+=Math.min(stamp-last,80)*.00016;
    last=stamp;
    const width=Math.round(canvas.clientWidth*Math.min(devicePixelRatio||1,1.5)),height=Math.round(canvas.clientHeight*Math.min(devicePixelRatio||1,1.5));
    if(!width||!height)return;
    if(canvas.width!==width||canvas.height!==height){canvas.width=width;canvas.height=height;}
    gl.viewport(0,0,width,height);gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);
    const f=1/Math.tan(.78/2),ratio=width/height,near=.1,far=20;
    gl.uniformMatrix4fv(gl.getUniformLocation(program,'projection'),false,new Float32Array([f/ratio,0,0,0,0,f,0,0,0,0,(far+near)/(near-far),-1,0,0,2*far*near/(near-far),0]));
    const drift=motion.matches?0:Math.sin(time)*.12;
    gl.uniform3f(gl.getUniformLocation(program,'color'),.07,.49,.84);
    gl.uniformMatrix4fv(gl.getUniformLocation(program,'model'),false,matrix(.56+rx,-.34+ry,-.30+drift,1,-4.2));gl.drawArrays(gl.TRIANGLES,0,vertices);
    gl.uniform3f(gl.getUniformLocation(program,'color'),.16,.77,.77);
    gl.uniformMatrix4fv(gl.getUniformLocation(program,'model'),false,matrix(-.68+rx,.48+ry,.65-drift,.82,-4.08));gl.drawArrays(gl.TRIANGLES,0,vertices);
    scene.setAttribute('data-model-ready','');
    if(!motion.matches)frame=requestAnimationFrame(draw);
  }
  function schedule(){if(frame)cancelAnimationFrame(frame);frame=0;last=0;if(visible&&!lost&&!document.hidden)frame=requestAnimationFrame(draw);}
  try {setup();} catch {return;}
  if('IntersectionObserver' in window){new IntersectionObserver(entries=>{visible=entries[0].isIntersecting;schedule();},{threshold:.05}).observe(scene);}else{visible=true;schedule();}
  if('ResizeObserver' in window)new ResizeObserver(schedule).observe(canvas);else addEventListener('resize',schedule);
  scene.addEventListener('pointermove',event=>{if(motion.matches||!pointer.matches)return;const r=scene.getBoundingClientRect();rx=(event.clientY-r.top-r.height/2)/r.height*.16;ry=(event.clientX-r.left-r.width/2)/r.width*.22;});
  scene.addEventListener('pointerleave',()=>{rx=ry=0;});
  canvas.addEventListener('webglcontextlost',event=>{event.preventDefault();lost=true;scene.removeAttribute('data-model-ready');schedule();});
  canvas.addEventListener('webglcontextrestored',()=>{try{setup();lost=false;schedule();}catch{lost=true;}});
  motion.addEventListener('change',()=>{rx=ry=0;schedule();});document.addEventListener('visibilitychange',schedule);
  addEventListener('pagehide',()=>{if(frame)cancelAnimationFrame(frame);frame=0;});addEventListener('pageshow',schedule);
})();
