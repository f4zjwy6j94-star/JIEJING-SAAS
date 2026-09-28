'use strict';
(function(root) {
  const defaults = Object.freeze({
    title:'6-Piece Travel Packing Cube Set - Sage, Beige and Charcoal',
    description:'Organise travel essentials with a coordinated six-piece packing cube set.\n\nThe reference shows sage, beige and charcoal pieces. Check the confirmed dimensions, material and care details before purchasing.',
    material:'', dimensions:'', weight:'', quantity:'', price:''
  });
  const fields = Object.keys(defaults);
  function create() {
    let saved = {...defaults};
    let draft = {...defaults};
    let cover = null;
    let reviews = {};
    let listingSaved = false;
    return {
      get saved(){return {...saved};},
      get draft(){return {...draft};},
      get cover(){return cover;},
      get listingSaved(){return listingSaved;},
      get dirty(){return fields.some(key=>draft[key] !== saved[key]);},
      edit(key,value){if(!fields.includes(key))return false; draft[key]=String(value);return true;},
      save(group){
        const keys = group === 'facts' ? ['material','dimensions','weight','quantity'] : ['title','description','price'];
        if(group !== 'facts' && (!draft.title.trim() || !draft.description.trim()))return {ok:false,error:'请先填写商品标题与描述。'};
        if(draft.title.length > 80)return {ok:false,error:'商品标题不能超过 80 个字符。'};
        const limits={weight:[1,100000,true],quantity:[1,999999,true],price:[.01,999999,false]};
        for(const key of keys){
          if(!limits[key] || !draft[key].trim())continue;
          const value=Number(draft[key]);const [min,max,integer]=limits[key];
          if(!Number.isFinite(value)||value<min||value>max||(integer&&!Number.isInteger(value)))return {ok:false,error:'请检查重量、库存或价格，填写有效的正数。'};
        }
        for(const key of keys)saved[key]=draft[key].trim();
        for(const key of keys)draft[key]=saved[key];
        if(group!=='facts')listingSaved=true;
        return {ok:true};
      },
      review(id,key,checked){
        if(!['appearance','rights','platform'].includes(key))return;
        reviews[id]={...reviews[id],[key]:!!checked};
        if(cover===id && !(reviews[id].appearance && reviews[id].rights && reviews[id].platform))cover=null;
      },
      getReview(id){return {appearance:false,rights:false,platform:false,...reviews[id]};},
      selectCover(id){
        if(!reviews[id]?.appearance||!reviews[id]?.rights||!reviews[id]?.platform)return false;
        cover=id;return true;
      },
      checks(){
        return [
          {key:'facts',label:'商品事实',ok:!!(saved.material&&saved.dimensions&&saved.weight&&saved.quantity),detail:'材质、尺寸、重量与可售数量',route:'facts'},
          {key:'listing',label:'Listing 草稿',ok:listingSaved&&!!saved.title&&!!saved.description,detail:'已保存的标题与描述',route:'listing'},
          {key:'price',label:'售价',ok:!!saved.price,detail:'由商家确定的销售价格',route:'listing'},
          {key:'media',label:'商品图片',ok:!!cover,detail:'已选用的封面与演示核对',route:'media'}
        ];
      },
      reset(){saved={...defaults};draft={...defaults};cover=null;reviews={};listingSaved=false;}
    };
  }
  root.JiejingDemoState = Object.freeze({create});
})(typeof window !== 'undefined' ? window : globalThis);
